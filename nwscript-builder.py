import sublime
import sublime_plugin

import subprocess
import threading
import multiprocessing
import os
import re
import time


class Script:
    nss = None
    ncs = None

    has_main = True
    dependencies = None

    # Cached mtime values to prevent excessive IO requests
    nss_mtime = None  # Set at the beginning of each build
    ncs_mtime = None  # Set on first run and after each compilation

class DirCache:
    # script name => Script object
    scripts = {}

    # script_name => set(scripts depending on script_name)
    reversed_deps = {}

    # Last build time
    last_build = 0.0


class nwscript_builder(sublime_plugin.WindowCommand):

    panel = None
    panel_lock = threading.Lock()

    started_processes = []
    build_lock = threading.Lock()
    stop_build = False

    # directory => DirCache
    cache = {}

    # Build results default settings
    encoding = "cp850"
    syntax = "Packages/STNeverwinterScript/nwscript.build-language"
    file_regex = "^\\s*?([^\\(]+)\\(([0-9]+)\\): (Error|Warning): .*?$"

    # Setup build results pane and start run_build in a side thread
    def run(self, build_all=False, **kargs):
        vars = self.window.extract_variables()
        if "file_path" not in vars:
            return
        working_dir = vars['file_path']

        with self.panel_lock:
            # Open results panel and configure it
            self.panel = self.window.create_output_panel('exec')

            self.panel.set_line_endings("Windows")
            self.panel.set_syntax_file(self.syntax)

            # Set regex
            settings = self.panel.settings()
            settings.set(
                "result_file_regex",
                self.file_regex
            )
            settings.set("result_base_dir", working_dir)

            self.window.run_command("show_panel", {"panel": "output.exec"})


        # Work in a separate thread to so main thread doesn't freeze
        threading.Thread(
            target=self.run_build,
            args=(working_dir, build_all)
        ).start()

    # Main build function
    def run_build(self, working_dir: str, build_all: bool):
        # Stop currently running processes
        if self.build_lock.locked():
            self.write_build_results("STOPPING CURRENT BUILD\n")
            self.stop_build = True
            for p in self.started_processes:
                p.terminate()
            self.build_lock.acquire()
            self.build_lock.release()
            self.stop_build = False
            self.write_build_results("STOPPED\n")

        with self.build_lock:
            # Get / create cache if needed
            dircache = self.cache.setdefault(working_dir, DirCache())

            # Save current time (dircache.last_build will be updated once build is finished)
            curr_build = time.time()

            self.write_build_results("Parsing scripts in %s...\n" % working_dir)
            # Fix scrolling issue
            self.panel.set_viewport_position((0, 0))

            # Build / update script list
            self.update_script_list(working_dir)

            # Get modified script + scripts using them
            if build_all:
                scripts_to_build = [sn for sn in dircache.scripts if dircache.scripts[sn].nss is not None]
            else:
                scripts_to_build = self.get_unbuilt_scripts(working_dir)

            if len(scripts_to_build) == 0:
                self.write_build_results("No scripts needs to be compiled\n")
                return

            self.write_build_results("%d scripts will be compiled: " % len(scripts_to_build))
            if len(scripts_to_build) < 100:
                self.write_build_results(", ".join(scripts_to_build) + "\n")
            else:
                self.write_build_results(", ".join(scripts_to_build[0:100]) + " and more... \n")
            self.write_build_results("-" * 80 + "\n")

            # Source files to compile
            src_to_build = [dircache.scripts[sn].nss for sn in scripts_to_build]

            # Build the scripts
            perf_build_start = time.time()

            status = self.compile_files(working_dir, src_to_build)

            perf_build_end = time.time()
            perf_build_duration = perf_build_end - perf_build_start

            if not self.stop_build:
                dircache.last_build = curr_build

            # Update NCS mtimes
            for sn in scripts_to_build:
                if dircache.scripts[sn].ncs is not None:
                    ncs_path = os.path.join(working_dir, dircache.scripts[sn].ncs)
                    dircache.scripts[sn].ncs_mtime = os.path.getmtime(ncs_path)

            # Statz
            time.sleep(0.5)
            self.write_build_results("-" * 80 + "\n")
            if status == 0:
                self.write_build_results(
                    "Finished smart build in %.1f seconds with no errors\n" % perf_build_duration
                )
            else:
                self.write_build_results(
                    "Finished smart build in %.1f seconds with some errors\n" % perf_build_duration
                )

    # List all scripts in workdir and update information in self.cache[workdir]
    def update_script_list(self, workdir: str):
        dircache = self.cache.setdefault(workdir, DirCache())

        # Find all scripts in workdir
        for filename in os.listdir(workdir):
            ext = os.path.splitext(filename)[1].lower()
            if ext == ".nss" or ext == ".ncs":
                filepath = os.path.join(workdir, filename)
                if not os.path.isfile(filepath):
                    continue

                script_name = os.path.splitext(filename)[0].lower()

                script = dircache.scripts.setdefault(script_name, Script())

                # TODO
                # # Cache include-only mtimes by calculating the max mtime of all dependent scripts HERE

                if ext == ".nss":
                    script.nss_mtime = os.path.getmtime(filepath)
                    if script.nss is None or script.nss_mtime > dircache.last_build:
                        # Script is unknown or has been modified, parse it
                        (script.has_main, script.dependencies) = self.parse_script(filepath)
                    script.nss = filename
                else:
                    script.ncs = filename

        # Update reversed dependency graph
        dircache.reversed_deps = {}
        for script_name, script in dircache.scripts.items():
            if script.nss is None:
                self.write_build_results("Note: script %s has no source file\n" % script_name)
            else:
                for dep in script.dependencies:
                    dircache.reversed_deps.setdefault(dep, set()).add(script_name)

    # Go through self.cache[workdir].scripts to extract all scripts that needs to be built based on
    # modification times of NSS vs NCS
    def get_unbuilt_scripts(self, workdir: str):
        dircache = self.cache[workdir]

        # Cached mtimes calculated by taking the oldest value from all dependencies
        include_ncs_mtimes = {}
        def get_ncs_mtime(script_name) -> float:
            script = dircache.scripts[script_name]
            if script.ncs_mtime is None:
                ncs = os.path.join(workdir, script.ncs)
                script.ncs_mtime = os.path.getmtime(ncs)
            return dircache.scripts[script_name].ncs_mtime

        # Get the oldest NCS mtime for a given script
        def get_oldest_ncs_mtime_for(script_name, explored=set()) -> float:
            if script_name not in dircache.scripts:
                self.write_build_results("Note: %s is not found in current directory\n" % script_name)
                return time.now()

            if dircache.scripts[script_name].has_main:
                # print(script_name, "has main")
                if dircache.scripts[script_name].ncs is not None:
                    # There is an existing NCS file
                    return get_ncs_mtime(script_name)
                else:
                    # Missing NCS file, we need to compile it
                    return 0.0
            else:
                # print(script_name, "has no main. dependent scripts:", dircache.reversed_deps.get(script_name, set()))
                if script_name in include_ncs_mtimes:
                    return include_ncs_mtimes[script_name]

                min_mtime = time.time()
                for sn in dircache.reversed_deps.get(script_name, set()):
                    if sn not in explored:
                        explored.add(sn)
                        mtime = get_oldest_ncs_mtime_for(sn, explored)
                        if mtime < min_mtime:
                            min_mtime = mtime

                include_ncs_mtimes[script_name] = min_mtime
                return min_mtime  # TODO: does not whork when modifying _misc

        # Create a list of scripts that have NCS files (or dependent NCS files) older than the NSS
        modified_scripts = []
        for script_name, script in dircache.scripts.items():
            if script.nss is None:
                continue

            if script.has_main:
                # Script has a main / Startingconditional function
                if script.ncs is None:
                    modified_scripts.append(script_name)
                else:
                    # if os.path.getmtime(nss) > get_ncs_mtime(script_name):
                    if script.nss_mtime > get_ncs_mtime(script_name):
                        modified_scripts.append(script_name)
            else:
                # Include only file
                latest_ncs_mtime = get_oldest_ncs_mtime_for(script_name)

                if script.nss_mtime > latest_ncs_mtime:
                    modified_scripts.append(script_name)

        self.write_build_results("%d scripts have been modified: " % len(modified_scripts))
        if len(modified_scripts) < 100:
            self.write_build_results(", ".join(modified_scripts) + "\n")
        else:
            self.write_build_results(", ".join(modified_scripts[0:100]) + " and more... \n")

        # Expand the modified_scripts by adding all dependent scripts
        scripts_to_build = set()
        explored_scripts = set()
        def add(script):
            if script in explored_scripts:
                return
            explored_scripts.add(script)

            if script in dircache.reversed_deps:
                # Script is an include script, try adding all script using it
                [add(s) for s in dircache.reversed_deps[script]]
            else:
                scripts_to_build.add(script)

        # do the expansion
        [add(s) for s in modified_scripts]

        return list(scripts_to_build)



    rgx_comment = re.compile(r'//.*?$|/\*.*?\*/', re.DOTALL | re.MULTILINE)
    rgx_include = re.compile(r'^\s*#\s*include\s+"(.+?)"', re.MULTILINE)
    rgx_main = re.compile(r'(void|int)\s+(main|StartingConditional)\s*\(.*?\)\s*\{', re.DOTALL | re.MULTILINE)

    # Parse a NSS file and extract include list and check if there is a main function
    def parse_script(self, filepath: str) -> (bool, list):
        with open(filepath, "r", encoding="utf-8", errors="ignore") as file:
            data = file.read()
            data = self.rgx_comment.sub("", data)

            has_main = self.rgx_main.search(data) is not None
            includes = [m.lower() for m in self.rgx_include.findall(data)]

            return (has_main, includes)

        return None

    # Compile many files by spreading them across multiple compiler processes
    def compile_files(self, working_dir, script_list: list):
        # Get compiler config
        settings = sublime.load_settings('nwscript.sublime-settings')
        compiler_cmd = settings.get("compiler_cmd")
        include_path = settings.get("include_path")
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
            self.write_build_results("nwscript-smartbuild error: %s\n" % e)

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
    def write_build_results(self, text):
        with self.panel_lock:
            self.panel.run_command("append", {"characters": text})


    def forward_output(self, handle):
        def queue_write(text):
            sublime.set_timeout(lambda: self.write_build_results(text), 1)

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
                queue_write(out.decode(self.encoding).replace("\r\n", "\n"))
                if data == b'':
                    raise IOError('EOF')
                out = b''
            except (UnicodeDecodeError) as e:
                queue_write("Error decoding output using %s - %s" % (
                    self.encoding, e
                ))
                break
            except (IOError):
                break
