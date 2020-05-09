import sublime
import sublime_plugin
import os
import re
import threading
from .nwscript_doc_fixes import get_doc_fix

class SymbolCompletions:
    file = None
    mtime = None
    dependencies = []
    completions = []

    documentation = []
    symbol_list = {}

class Documentation:
    signature = None  # tuple containing type, name and args
    script_resref = None
    fix = None  # (severity, text)
    text = None

    def format_popup(self):

        fix_html = ""
        if self.fix is not None:
            color = {
                "Broken": "#f00",
                "Warning": "#ff0",
                "Note": "#888",
            }.get(self.fix[0], "#fff")

            fix_html = """
                <div style="border-left: 0.5em solid {color}; padding-left: 1em">
                    <h3 style="color: {color}">{severity}</h3>
                    <p>{text}</p>
                </div>
            """.format(severity=self.fix[0], color=color, text=self.fix[1])

        text_html = "<br>".join([line[2:] for line in self.text.splitlines()]) if self.text is not None else ""
        location = "defined in " + self.script_resref if self.script_resref != "nwscript" else "built-in function"

        args_list = self.signature[2].split(", ")
        args_html = "<br>\t" + ",<br>\t".join(args_list) + "<br>" if len(args_list) > 3 else self.signature[2]

        return """
        <body style="padding: 0.3em">
            <div style="padding: 0.5em;">
                {self.signature[0]} <strong>{self.signature[1]}</strong>({args_html})
                <div style="padding-left: 1em; color: color(var(--foreground) alpha(0.5));"><em>{location}</em></div>
            </div>
            {fix_html}
            <p>{text_html}</p>
        </body>
        """.format(self=self, fix_html=fix_html, text_html=text_html, location=location, args_html=args_html)


class NWScriptCompletion(sublime_plugin.EventListener):

    settings = sublime.load_settings('nwscript.sublime-settings')

    # script resref => SymbolCompletions
    symbol_completions = None

    # Set of include-only files
    include_completions = None

    def on_query_completions(self, view: sublime.View, prefix: str, locations: (str, str, (int, int))) -> list:
        if not view.scope_name(locations[0]).startswith("source.nss"):
            return

        position = locations[0]
        position = position - len(prefix)
        if (view.substr(position) != '.'):
            position = locations[0]

        file_path = view.file_name()
        file_data = view.substr(sublime.Region(0, view.size()))
        module_path = os.path.dirname(file_path)

        self.parse_script_tree(module_path, file_path, file_data)

        # Handle #include completions
        row, col = view.rowcol(position)
        line = view.substr(sublime.Region(view.text_point(row, 0), position))

        if self.rgx_include_partial.match(line) is not None:
            return (
                self.get_include_completions(module_path),
                sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS
            )

        # Handle symbol completions
        return self.gather_symbol_completions(self.get_resref(file_path))

    def on_modified(self, view: sublime.View) -> None:
        point = view.sel()[0].begin()
        if not view.scope_name(point).startswith("source.nss"):
            return

        if self.settings.get("enable_doc_popup") is False:
            return

        file_path = view.file_name()
        file_data = view.substr(sublime.Region(0, view.size()))
        module_path = os.path.dirname(file_path)

        if self.settings.get("parse_on_modified") is True:
            self.parse_script_tree(module_path, file_path, file_data)

        if view.substr(point) in ['(', ')'] or point != view.sel()[0].end():
            point -= 1

        self.show_doc_popup_for(
            view,
            resref=self.get_resref(file_path),
            symbol=view.substr(view.word(point)),
        )

    def on_hover(self, view: sublime.View, point: tuple, hover_zone) -> None:
        if hover_zone != sublime.HOVER_TEXT:
            return
        if not view.scope_name(point).startswith("source.nss"):
            return

        if self.settings.get("enable_doc_popup") is False:
            return

        # Ignore hover over non selected text
        selection = view.sel()[0]
        if not selection.contains(point):
            return

        symbol = view.substr(view.word(point))
        if view.substr(selection) != symbol:
            return

        file_path = view.file_name()
        module_path = os.path.dirname(file_path)

        self.parse_script_tree(module_path, file_path, view.substr(sublime.Region(0, view.size())))

        self.show_doc_popup_for(
            view,
            resref=self.get_resref(view.file_name()),
            symbol=symbol,
        )


    @staticmethod
    def get_resref(file_path: str) -> str:
        return os.path.splitext(os.path.basename(file_path))[0]

    def show_doc_popup_for(self, view, resref, symbol) -> bool:
        doc = self.get_documentation(resref, symbol)
        if doc is not None:
            view.show_popup(
                doc.format_popup(),
                location=-1, max_width=600, flags=sublime.COOPERATE_WITH_AUTO_COMPLETE
            )
            return True
        return False

    def get_documentation(self, resref: str, symbol: str) -> Documentation:
        explored_resrefs = set()

        def recurr_get_documentation(curr_resref) -> Documentation:
            if curr_resref not in self.symbol_completions:
                return None
            compl = self.symbol_completions[curr_resref]

            if symbol in compl.symbol_list:
                return compl.documentation[compl.symbol_list[symbol]]

            for dep in compl.dependencies:
                if dep not in explored_resrefs:
                    explored_resrefs.add(dep)
                    doc = recurr_get_documentation(dep)
                    if doc is not None:
                        return doc

            return None

        explored_resrefs.add("nwscript")
        doc = recurr_get_documentation("nwscript")
        if doc is not None:
            return doc

        doc = recurr_get_documentation(resref)
        if doc is not None:
            return doc
        return None

    def gather_symbol_completions(self, resref: str) -> list:
        ret = []

        explored_resrefs = set("nwscript")
        ret.extend(self.symbol_completions["nwscript"].completions)

        def recurr_gather_symbol_completions(curr_resref):
            compl = self.symbol_completions[curr_resref]
            ret.extend(compl.completions)

            for dep in compl.dependencies:
                if dep not in explored_resrefs:
                    explored_resrefs.add(dep)
                    recurr_gather_symbol_completions(dep)

        explored_resrefs.add(resref)
        recurr_gather_symbol_completions(resref)
        return ret

    # Search through include dirs and module path to find a file matching resref
    def find_file_by_resref(self, module_path: str, resref: str) -> str:
        path_list = [module_path] + self.settings.get("include_path")
        for path in path_list:
            file = os.path.join(path, resref + ".nss")
            if os.path.isfile(file):
                return file

            if os.name == "posix":
                file = os.path.join(path, resref + ".NSS")
                if os.path.isfile(file):
                    return file

        print("nwscript-completion: could not find '" + resref + "' in ", path_list)
        return None


    # Parse a script and its dependencies if they have been modified since last call
    def parse_script_tree(self, module_path: str, file_path: str, file_data: str = None) -> None:
        if self.symbol_completions is None:
            self.symbol_completions = {}
        if self.include_completions is None:
            self.init_include_list(module_path)

        explored_resrefs = set("nwscript")
        if "nwscript" not in self.symbol_completions:
            self.parse_script(self.find_file_by_resref(module_path, "nwscript"))

        def recurr_parse(file):
            resref = self.get_resref(file)
            compl = self.symbol_completions.get(resref, None)

            if compl is None or os.path.getmtime(file) > compl.mtime:
                resref, compl = self.parse_script(file)

            for dep in compl.dependencies:
                if dep not in explored_resrefs:
                    explored_resrefs.add(dep)
                    dep_resref = self.find_file_by_resref(module_path, dep)
                    if dep_resref is not None:
                        recurr_parse(dep_resref)

        start_resref = self.get_resref(file_path)
        explored_resrefs.add(start_resref)
        if file_data is not None:
            self.parse_script(file_path, file_data)
        recurr_parse(file_path)


    # Parse a single script and extract completion info
    def parse_script(self, file_path: str, file_data: str = None) -> None:
        if file_data is None:
            file_data = open(file_path, encoding="utf-8", errors="ignore").read()

        compl = SymbolCompletions()
        compl.file = file_path
        compl.mtime = os.path.getmtime(file_path)
        compl.dependencies = self.rgx_include.findall(file_data)
        compl.completions = []
        compl.documentation = []
        compl.symbol_list = {}
        has_main = False

        resref = self.get_resref(file_path)
        custom_mark = "⋄" if resref != "nwscript" else ""

        # Function completion
        for (fun_doc, fun_type, fun_name, fun_args) in self.rgx_fun.findall(file_data):
            if fun_name in ("main", "StartingConditional"):
                has_main = True
            else:
                # Parse function arguments
                args_list = []
                i = 0
                if fun_args != "" and not fun_args.isspace():
                    for arg in fun_args.split(","):
                        arg_match_obj = self.rgx_fun_arg.search(arg)
                        if arg_match_obj is None:
                            print("nwscript-completion: Could not parse argument '%s' in %s.%s" % (
                                arg, resref, fun_name
                            ))
                            arg_match_obj = None
                        else:
                            arg_match = arg_match_obj.groups()
                            default = ""
                            if arg_match[2] is not None:
                                default += "=" + arg_match[2]
                            args_list.append("${%d:%s %s}" % (i + 1, arg_match[0], arg_match[1] + default))
                        i = i + 1

                if fun_name not in compl.symbol_list:
                    # Register new symbol
                    compl.symbol_list[fun_name] = len(compl.completions)
                    compl.completions.append([
                        "%s\t%s()" % (fun_name, custom_mark + fun_type),
                        "%s(%s)" % (fun_name, ", ".join(args_list))
                    ])

                    doc = Documentation()
                    doc.signature = (fun_type, fun_name, fun_args)
                    doc.script_resref = resref
                    doc.fix = get_doc_fix(resref, fun_name)
                    doc.text = fun_doc if fun_doc != "" and not fun_args.isspace() else None
                    compl.documentation.append(doc)
                else:
                    # Set documentation if none
                    existing_index = compl.symbol_list[fun_name]
                    existing_doc = compl.documentation[existing_index]
                    if existing_doc.text is None:
                        existing_doc.text = fun_doc if fun_doc != "" and not fun_args.isspace() else None

        # const completions
        glob_rgx = self.rgx_global_nwscript if resref == "nwscript" else self.rgx_global_const
        for (glob_type, glob_name, glob_value) in glob_rgx.findall(file_data):
            compl.completions.append([glob_name + "\t" + glob_type + "=" + glob_value, glob_name])
            compl.documentation.append(None)

        # #define completions
        for (def_name, def_value) in self.rgx_fun_define.findall(file_data):
            compl.completions.append([def_name + "\t" + def_value, def_name])
            compl.documentation.append(None)

        # update include completions
        if self.include_completions is not None:
            if has_main:
                self.include_completions.add(resref)
            else:
                self.include_completions.discard(resref)

        self.symbol_completions[resref] = compl
        return (resref, compl)


    def init_include_list(self, module_path):
        if self.include_completions is not None:
            return

        sublime.active_window().status_message("Building #include completions...")

        def worker():
            print("nwscript-completion: Parsing include completions")
            self.include_completions = set()
            for folder in [module_path] + self.settings.get("include_path"):
                for filename in os.listdir(folder):
                    ext = os.path.splitext(filename)[1].lower()
                    if ext != ".nss":
                        continue
                    file_path = os.path.join(folder, filename)
                    if not os.path.isfile(file_path):
                        continue

                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        data = f.read()
                        data = self.rgx_comment.sub("", data)
                        has_main = self.rgx_main.search(data) is not None

                        if not has_main:
                            self.include_completions.add(os.path.splitext(filename)[0])

            sublime.active_window().status_message("Building #include completions... Done !")

        threading.Thread(
            target=worker,
            args=()
        ).start()

    def get_include_completions(self, module_path):
        self.init_include_list(module_path)
        return [[resref + "\tscript", resref] for resref in self.include_completions]


    nwn_types = r'(void|string|int|float|object|vector|location|effect|event|talent|itemproperty|action|struct\s+\w+)'
    rgx_fun = re.compile(
        r'((?:^[ \t]*//[^\n]*?\n)*)'
        r'^[ \t]*' + nwn_types + r'\s+'
        r'(\w+)\s*'
        r'\(([^)]*?)\)\s*[;\{]',
        re.DOTALL | re.MULTILINE)

    rgx_fun_arg = re.compile(
        nwn_types + r'\s+'
        r'(\w+)'
        r'(?:\s*=\s*([-\w\."]+))?',
        re.DOTALL)

    rgx_global_const = re.compile(
        r'^\s*const\s+'
        + nwn_types + r'\s+'
        r'(\w+)'
        r'\s*=\s*(.+?)\s*;',
        re.DOTALL | re.MULTILINE)
    rgx_global_nwscript = re.compile(
        r'^\s*' + nwn_types + r'\s+'
        r'(\w+)'
        r'\s*=\s*(.+?)\s*;',
        re.DOTALL | re.MULTILINE)

    rgx_fun_define = re.compile(
        r'^\s*#\s*define\s+(\w+)\s+(.+?)\s*$',
        re.DOTALL | re.MULTILINE)

    rgx_include = re.compile(
        r'^(?!\s*//)\s*#include\s+"([\w-]+)"',
        re.MULTILINE)

    rgx_comment = re.compile(r'/\*.*?\*/|//[^\n]*', re.DOTALL)
    rgx_multiline_comment = re.compile(r'/\*.*?\*/', re.DOTALL)
    rgx_include_partial = re.compile(
        r'^(?!\s*//)\s*#include\s+"([\w-]*)',
        re.MULTILINE)
    rgx_main = re.compile(
        r'^[ \t]*(?:int|void)\s+'
        r'(main|StartingConditional)\s*'
        r'\(([^)]*?)\)\s*\{',
        re.DOTALL | re.MULTILINE)
