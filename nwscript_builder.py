import sublime
import sublime_plugin

import subprocess
import threading
import multiprocessing
import os
import re
import time

def plugin_loaded():
    nwscript_builder.settings = sublime.load_settings('nwscript.sublime-settings')

class Script:
    def __init__(self):
        # File relative paths (mostly for Linux compatibility)
        self.nss = None
        self.ncs = None

        # True if the file has no main function
        self.is_library = False

        # List of script dependencies
        self.dependencies = None

        # Modification time of NSS and NCS files
        self.nss_mtime = None
        self.ncs_mtime = None

        # Set when there is a missing source file
        # True if the NCS file is meant to be run by NWNScriptAccelerator nwnx4 plugin
        self.ncs_is_native = None

class DirCache:
    def __init__(self):
        # script name => Script object
        self.scripts = {}


class nwscript_builder(sublime_plugin.WindowCommand):
    settings = None

    def __init__(self, window: sublime.Window):
        super().__init__(window)

        self.panel = None
        self.panel_lock = threading.Lock()

        self.started_processes = []
        self.build_lock = threading.Lock()
        self.stop_build = False

        # directory => DirCache
        self.cache = {}
        self.cached_include_paths = None



    # Setup build results pane and start run_build in a side thread
    def run(self, build_type="smart", kill=False, **kargs):
        vars = self.window.extract_variables()
        if "file_path" not in vars:
            return
        working_dir = vars['file_path']

        if kill is True:
            build_type = "kill"
        else:
            with self.panel_lock:
                # Open results panel and configure it
                self.panel = self.window.create_output_panel('exec')

                self.panel.set_line_endings("Windows")
                self.panel.set_syntax_file(
                    "Packages/Neverwinter Script syntax and build/nwnscriptcompiler.sublime-syntax"
                )

                # Set regex
                settings = self.panel.settings()
                settings.set('word_wrap', True)
                settings.set(
                    "result_file_regex",
                    "^\\s*?([^\\(]+)\\(([0-9]+)\\): (Error|Warning): .*?$"
                )
                settings.set("result_base_dir", working_dir)

                self.window.run_command("show_panel", {"panel": "output.exec"})


        # Work in a separate thread to so main thread doesn't freeze
        threading.Thread(
            target=self.run_build,
            args=(working_dir, build_type)
        ).start()

    # Main build function
    def run_build(self, working_dir: str, build_type: str):
        # Stop currently running processes
        if self.build_lock.locked():
            self.print_build_results("STOPPING CURRENT BUILD\n")
            self.stop_build = True
            for p in self.started_processes:
                p.terminate()
            self.build_lock.acquire()
            self.build_lock.release()
            self.stop_build = False
            self.print_build_results("STOPPED\n")

        if build_type == "kill":
            return

        with self.build_lock:
            # Fix scrolling issue
            self.print_build_results("\n")
            self.panel.set_viewport_position((0, 0))

            if build_type == "single":
                vars = self.window.extract_variables()
                src_to_build = [vars['file']]
            else:
                # Parse scripts in include paths (will be done only the first time)
                self.init_includes_cache()

                # Update module script list
                self.update_script_list(working_dir)

                # Cache is now built
                dircache = self.cache[working_dir]

                # Get modified script + scripts using them
                if build_type == "all":
                    scripts_to_build = [sn for sn in dircache.scripts if dircache.scripts[sn].nss is not None]
                elif build_type == "smart":
                    scripts_to_build = self.get_unbuilt_scripts(working_dir)
                else:
                    self.print_build_results("Unknown build type: '%s'\n" % build_type)
                    return

                if len(scripts_to_build) == 0:
                    self.print_build_results("=> No scripts needs to be compiled\n")
                    return

                self.print_build_results("=> %d scripts will be compiled\n" % len(scripts_to_build))

                # Source files to compile
                src_to_build = [dircache.scripts[sn].nss for sn in scripts_to_build]

            self.print_build_results(" Starting compilation ".center(80, "=") + "\n")

            # Build the scripts
            perf_build_start = time.time()

            status = self.compile_files(working_dir, src_to_build)

            perf_build_end = time.time()
            perf_build_duration = perf_build_end - perf_build_start

            # Statz
            time.sleep(0.1)
            self.print_build_results(" Compilation ended ".center(80, "=") + "\n")
            if status == 0:
                self.print_build_results(
                    "Finished %s build in %.1f seconds\n" % (build_type, perf_build_duration)
                )
            else:
                self.print_build_results(
                    "Finished %s build in %.1f seconds with some errors\n" % (build_type, perf_build_duration)
                )


    def init_includes_cache(self) -> None:
        cache = self.settings.get("include_path")

        # Check if include list changed
        if self.cached_include_paths == cache:
            return

        # Remove previous cache
        if self.cached_include_paths is not None:
            for path in self.cached_include_paths:
                self.cache.pop(path, None)

        # Save include path list
        self.cached_include_paths = cache.copy()

        # Build simple cache (only parse NSS files)
        for folder in self.cached_include_paths:
            self.print_build_results("Parsing scripts in include path %s...\n" % folder)
            dircache = self.cache.setdefault(folder, DirCache())

            for filename in os.listdir(folder):
                if os.path.splitext(filename)[1].lower() != ".nss":
                    continue
                filepath = os.path.join(folder, filename)
                if not os.path.isfile(filepath):
                    continue
                script_name = os.path.splitext(filename)[0].lower()

                script = dircache.scripts.setdefault(script_name, Script())
                script.nss = filepath
                script.is_library, script.dependencies = self.parse_nss(filepath)
                script.nss_mtime = 0.0


    # List all scripts in workdir and update information in self.cache[workdir]
    def update_script_list(self, workdir: str) -> None:
        self.print_build_results("Parsing scripts in %s...\n" % workdir)
        dircache = self.cache.setdefault(workdir, DirCache())

        found_nss = set()
        found_ncs = set()

        # Find all scripts in workdir
        for filename in os.listdir(workdir):
            ext = os.path.splitext(filename)[1].lower()
            if ext in [".nss", ".ncs"]:
                filepath = os.path.join(workdir, filename)
                if not os.path.isfile(filepath):
                    continue

                script_name = os.path.splitext(filename)[0].lower()
                script = dircache.scripts.setdefault(script_name, Script())
                mtime = os.path.getmtime(filepath)

                if ext == ".nss":
                    if script.nss is None or mtime > script.nss_mtime:
                        # Script is unknown or has been modified, parse it
                        script.is_library, script.dependencies = self.parse_nss(filepath)
                    script.nss = filename
                    script.nss_mtime = mtime
                    found_nss.add(script_name)
                else:
                    script.ncs = filename
                    script.ncs_mtime = mtime
                    found_ncs.add(script_name)

        # Remove deleted files from cache
        to_be_removed = set()
        for script_name in dircache.scripts:
            if script_name not in found_nss:
                dircache.scripts[script_name].nss = None
            if script_name not in found_ncs:
                dircache.scripts[script_name].ncs = None
            if dircache.scripts[script_name].nss is None and dircache.scripts[script_name].ncs is None:
                to_be_removed.add(script_name)
        [dircache.scripts.pop(sn) for sn in to_be_removed]

        # Find scripts with missing source files
        no_source_scripts = []
        for script_name, script in dircache.scripts.items():
            if script.nss is None:
                if script.ncs_is_native is None:
                    # Parse NCS file to know if it should have an associated NSS file
                    script.ncs_is_native = self.parse_ncs(os.path.join(workdir, script.ncs))

                if script.ncs_is_native is False:
                    no_source_scripts.append(script_name)

        if len(no_source_scripts) > 0:
            self.print_build_results(
                "Warning: The following scripts have missing source files: %s\n"
                % self.script_list_to_str(no_source_scripts)
            )


    # Go through self.cache[workdir].scripts to extract all scripts that needs to be built based on
    # modification times of NSS vs NCS
    def get_unbuilt_scripts(self, workdir: str) -> set:
        dircache = self.cache[workdir]

        # Utility function to check if a script's dependencies are newer than
        # its build time, and requires to be re-built
        cached_nss_mtimes = {}
        def get_deps_latest_nss_mtime(script_name) -> float:
            def recurr_get_deps_latest_nss_mtime(curr_script_name, included_from, explored_scripts=None) -> float:
                if explored_scripts is None:
                    explored_scripts = set()

                if curr_script_name in cached_nss_mtimes:
                    return cached_nss_mtimes[curr_script_name]

                ret = 0.0
                explored_scripts.add(curr_script_name)

                curr_script = self.find_script_by_name(workdir, curr_script_name)
                if curr_script is None:
                    # Script is not found. Assume the dependency is changed to
                    # force build error
                    self.print_build_results(
                        "Warning: could not find script '%s', included in '%s'\n" % (curr_script_name, included_from)
                    )
                    ret = time.time()
                else:
                    ret = curr_script.nss_mtime

                    for dep in curr_script.dependencies:
                        if dep in explored_scripts:
                            continue

                        mtime = recurr_get_deps_latest_nss_mtime(dep, curr_script_name, explored_scripts)
                        if mtime > ret:
                            ret = mtime

                cached_nss_mtimes[curr_script_name] = ret
                return ret

            latest = 0.0
            for dep in dircache.scripts[script_name].dependencies:
                mtime = recurr_get_deps_latest_nss_mtime(dep, script_name)
                if mtime > latest:
                    latest = mtime

            return latest


        # Algorithm:
        # - Go through all known scripts
        #   - if it's not a library, ie has a main function:
        #     - if nss mtime > ncs mtime => build it
        #     - go through all its dependencies
        #       - if the dependency nss mtime > this script's ncs mtime => build it
        #   - if it's a library
        #     - Simply ignore
        #
        scripts_to_build = [set(), set(), set()]
        for script_name, script in dircache.scripts.items():
            if script.nss is not None and not script.is_library:
                # Script has source code and a main function
                if script.ncs is None:
                    # Script has never been built
                    scripts_to_build[0].add(script_name)
                elif script.nss_mtime > script.ncs_mtime:
                    # Script has been modified
                    scripts_to_build[1].add(script_name)
                elif get_deps_latest_nss_mtime(script_name) > script.ncs_mtime:
                    # One of its dependencies have been modified
                    scripts_to_build[2].add(script_name)

        self.print_build_results(
            "%d scripts with missing NCS: %s\n"
            % (len(scripts_to_build[0]), self.script_list_to_str(scripts_to_build[0]))
            + "%d scripts with outdated NCS: %s\n"
            % (len(scripts_to_build[1]), self.script_list_to_str(scripts_to_build[1]))
            + "%d scripts impacted by a dependency change: %s\n"
            % (len(scripts_to_build[2]), self.script_list_to_str(scripts_to_build[2]))
        )

        return scripts_to_build[0] | scripts_to_build[1] | scripts_to_build[2]

    # Search through current dir and include paths to find a given script
    def find_script_by_name(self, working_dir, script_name) -> Script:
        for folder in [working_dir] + self.settings.get("include_path"):
            script = self.cache[folder].scripts.get(script_name, None)
            if script is not None:
                return script
        return None


    rgx_comment = re.compile(r'//.*?$|/\*.*?\*/', re.DOTALL | re.MULTILINE)
    rgx_include = re.compile(r'^\s*#\s*include\s+"(.+?)(?:\.nss)?"', re.MULTILINE)
    rgx_main = re.compile(r'(void|int)\s+(main|StartingConditional)\s*\(.*?\)\s*\{', re.DOTALL)

    # Parse a NSS file and extract include list and check if there is a main function
    def parse_nss(self, filepath: str) -> (bool, list):
        with open(filepath, "r", encoding="utf-8", errors="ignore") as file:
            data = file.read()
            data = self.rgx_comment.sub("", data)

            is_library = self.rgx_main.search(data) is None
            dependencies = [m.lower() for m in self.rgx_include.findall(data)]

            return (is_library, dependencies)

    # Parse a NCS file and return if it is a native script for the NWNScriptAccelerator nwnx4 plugin
    @staticmethod
    def parse_ncs(file_path: str) -> bool:
        with open(file_path, "rb") as file:
            header = file.read(0x3f)
            if len(header) == 0x3f and header[0x1B: 0x3f] == b"NWScript Platform Native Script v1.0":
                return True
            return False

    # Compile many files by spreading them across multiple compiler processes
    def compile_files(self, working_dir, script_list: list):
        # Get compiler config
        compiler_cmd = self.settings.get("compiler_cmd")
        include_path = self.settings.get("include_path")
        include_args = []
        for inc in include_path:
            include_args.extend(["-i", inc])

        self.started_processes = []
        def count_running_processes():
            ret = 0
            for p in self.started_processes:
                if p.poll() is None:
                    ret += 1
            return ret

        try:
            while len(script_list) > 0 and not self.stop_build:
                # Take out scripts to build in this iteration
                scripts_to_process = script_list[0: min(30, len(script_list))]
                script_list = script_list[len(scripts_to_process):]

                # Build command-line
                args = compiler_cmd + include_args + [
                    "-v169", "-q", "-g", "-e", "-o", "-y",
                    "-r", working_dir,
                    "-b", working_dir,
                ]
                args.extend(scripts_to_process)

                # Windows only: prevent cmd from showing on screen
                si = None
                if os.name == 'nt':
                    si = subprocess.STARTUPINFO()
                    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW

                # Start compiler process
                proc = subprocess.Popen(
                    args,
                    cwd=working_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=False,
                    startupinfo=si,
                )
                self.started_processes.append(proc)

                # Redirect stdout & stderr to build results
                threading.Thread(
                    target=self.forward_output,
                    args=(proc.stdout,)
                ).start()
                threading.Thread(
                    target=self.forward_output,
                    args=(proc.stderr,)
                ).start()

                # Limit number of concurrent subprocesses
                while count_running_processes() >= multiprocessing.cpu_count():
                    time.sleep(0.1)

        except Exception as e:
            self.print_build_results("nwscript-smartbuild error: %s\n" % e)

        # Wait for subprocesses to end
        status = 0
        for proc in self.started_processes:
            ret = proc.wait()
            if ret != 0:
                status = ret

        self.started_processes = []

        # Return 0 if no error, otherwise != 0
        return status

    # Write to build results panel
    def print_build_results(self, text):
        with self.panel_lock:
            self.panel.run_command("append", {"characters": text})


    def forward_output(self, handle):
        def queue_write(text):
            sublime.set_timeout(lambda: self.print_build_results(text), 1)

        chunk_size = 2 ** 13
        out = b''
        while True:
            try:
                data = os.read(handle.fileno(), chunk_size)
                # If exactly the requested number of bytes was
                # read, there may be more data, and the current
                # data may contain part of a multibyte char
                out += data
                if len(data) == chunk_size:
                    continue
                if data == b'' and out == b'':
                    raise IOError('EOF')
                # We pass out to a function to ensure the
                # timeout gets the value of out right now,
                # rather than a future (mutated) version
                queue_write(out.decode("cp850").replace("\r\n", "\n"))
                if data == b'':
                    raise IOError('EOF')
                out = b''
            except (UnicodeDecodeError) as e:
                queue_write("Error decoding output using %s - %s" % (
                    "cp850", e
                ))
                break
            except (IOError):
                break


    @staticmethod
    def script_list_to_str(lst: list):
        if len(lst) < 100:
            return ", ".join(lst)
        return ", ".join(list(lst)[0:100]) + " and more..."
