import sublime
import sublime_plugin

import subprocess
import threading
import multiprocessing
import os
import re
import glob
import time
from itertools import chain


class DependencyInfo:
    # script name => list of files that include this script
    dependent_scripts = None
    # script name => list of included scripts (dependencies)
    script_dependencies = None
    # Last build time
    last_build = 0.0


class nwscript_builder(sublime_plugin.WindowCommand):

    panel = None
    panel_lock = threading.Lock()

    started_processes = []
    build_lock = threading.Lock()
    stop_build = False

    rgx_include = re.compile(r'^\s*#\s*include\s+"(.+?)"')

    # directory => DependencyInfo
    cache = {}

    encoding = "cp850"
    syntax = "Packages/STNeverwinterScript/nwscript.build-language"
    file_regex = "^\\s*?([^\\(]+)\\(([0-9]+)\\): (Error|Warning): .*?$"


    def run(self, build_all=False, **kargs):
        vars = self.window.extract_variables()
        if "file_path" not in vars:
            return
        working_dir = vars['file_path']

        if working_dir not in self.cache:
            self.cache[working_dir] = DependencyInfo()

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
            target=self.update_and_build,
            args=(working_dir, build_all)
        ).start()


    def update_and_build(self, working_dir, build_all):
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
            first_time_build = self.cache[working_dir].last_build == 0.0

            # Update time of last build
            since = self.cache[working_dir].last_build
            self.cache[working_dir].last_build = time.time()

            script_list = set()
            if build_all is False:
                # Parse nss files to update dependent_scripts and script_dependencies
                modified_list = self.update_include_graph(working_dir, since)

                # Go through the include graph to find files that needs to be re-built
                include_list = set()
                def add_script(script):
                    if script not in self.cache[working_dir].dependent_scripts:
                        # Script is not included elsewhere, probably has a main() function
                        script_list.add(script)
                    else:
                        # Script is included by several other scripts
                        if script not in include_list:
                            include_list.add(script)
                            for s in self.cache[working_dir].dependent_scripts[script]:
                                add_script(s)

                for s in modified_list:
                    add_script(s)

            else:
                # Add every script file in the working directory
                self.cache[working_dir].last_build = time.time()
                for filepath in glob.iglob(os.path.join(working_dir, "*.nss")):
                    script_name = os.path.splitext(os.path.basename(filepath))[0]
                    script_list.add(script_name)


            # Do nothing if there's nothing to do :)
            if len(script_list) == 0:
                self.write_build_results("No scripts to build")
                return

            # Replace script names with paths
            script_list = [os.path.join(working_dir, name + ".nss") for name in script_list]

            if first_time_build or build_all:
                self.write_build_results("Full build: %d scripts will be re-compiled\n" % len(script_list))
            else:
                self.write_build_results("%d script(s) to compile: %s\n" % (
                    len(script_list),
                    ", ".join([os.path.splitext(os.path.basename(f))[0] for f in script_list]),
                ))
            self.write_build_results("-" * 80 + "\n")


            # Build the scripts
            build_start = time.time()

            status = self.compile_script_list(working_dir, script_list)

            build_end = time.time()
            build_duration = build_end - build_start

            # Statz
            time.sleep(0.5)
            self.write_build_results("-" * 80 + "\n")
            if status == 0:
                self.write_build_results("Finished smart build in %.1f seconds with no errors\n" % build_duration)
            else:
                self.write_build_results("Finished smart build in %.1f seconds with some errors\n" % build_duration)

    def compile_script_list(self, working_dir, script_list: list):
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
                    time.sleep(1)

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


    # since: date of the last incremental or full build
    def update_include_graph(self, directory, since):
        first_time = self.cache[directory].script_dependencies is None
        if first_time:
            self.cache[directory].script_dependencies = {}
            self.cache[directory].dependent_scripts = {}
            self.write_build_results("Building dependency graph for the first time...\n")
        else:
            self.write_build_results("Updating dependency graph...\n")

        modified_files = []

        for filepath in glob.iglob(os.path.join(directory, "*.nss")):
            mtime = os.path.getmtime(filepath)
            if mtime > since or first_time:
                script_name = os.path.splitext(os.path.basename(filepath))[0]

                if mtime > since:
                    modified_files.append(script_name)

                # Read file to find #include directives
                with open(filepath, "r", encoding="utf-8", errors="ignore") as file:

                    previous_includes = set(self.cache[directory].script_dependencies.get(script_name, []))
                    new_includes = set()

                    # Find includes in the new version of the file
                    for line in file:
                        m = self.rgx_include.match(line)
                        if m:
                            new_includes.add(m.group(1))

                    # Update dependent_scripts and script_dependencies
                    added_includes = new_includes - previous_includes
                    removed_includes = previous_includes - new_includes

                    for inc in removed_includes:
                        self.cache[directory].dependent_scripts[inc].remove(script_name)

                    for inc in added_includes:
                        if inc not in self.cache[directory].dependent_scripts:
                            self.cache[directory].dependent_scripts[inc] = []
                        self.cache[directory].dependent_scripts[inc].append(script_name)

                    self.cache[directory].script_dependencies[script_name] = new_includes

        if first_time:
            self.write_build_results("  %d include-only scripts\n" % len(self.cache[directory].dependent_scripts))
        else:
            self.write_build_results("  %d modified files: %s\n" % (len(modified_files), modified_files))

        return modified_files


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
