import sublime
import sublime_plugin
import os
import re
import time
import threading
from .nwscript_doc_fixes import get_doc_fix

def plugin_loaded():
    NWScriptCompletion.settings = sublime.load_settings('nwscript.sublime-settings')

class SymbolCompletions:
    def __init__(self):
        self.file = None
        self.mtime = None
        self.dependencies = []
        self.completions = []

        self.documentation = []
        self.symbol_list = {}

        self.structs = []
        self.structs_doc = {}

class Documentation:
    def __init__(self):
        self.signature = None  # tuple containing type, name and args
        self.script_resref = None
        self.fix = None  # (severity, text)
        self.text = None

    def format_popup(self):

        fix_html = ""
        fix_color = None
        if self.fix is not None:
            fix_color = {
                "Broken": "#f00",
                "Warning": "#ff0",
                "Note": "#888",
            }.get(self.fix[0], "#fff")

            fix_html = """
                <div style="border-left: 0.5em solid {color}; padding-left: 0.5em">
                    <p>
                        <strong style="color: {color}">{severity}</strong><br>
                        {text}
                    </p>
                </div>
            """.format(
                severity=self.fix[0],
                color="color(var(--foreground) blend(%s 25%%))" % fix_color,
                text=self.fix[1]
            )

        symbol_type_name = None
        signature_html = None
        if self.signature[0] == "f":
            # function
            args_list = self.signature[3].split(", ")
            if len(self.signature[1]) + len(self.signature[2]) + len(self.signature[3]) + 3 > 80:
                args_html = "<br>\t" + ",<br>\t".join(args_list) + "<br>"
            else:
                args_html = self.signature[3]

            symbol_type_name = "function"
            signature_html = "%s <strong>%s</strong>(%s)" % (
                self.signature[1], self.signature[2], args_html
            )

        elif self.signature[0] == "c":
            # constant
            symbol_type_name = "constant"
            signature_html = "const %s <strong>%s</strong> = %s" % (
                self.signature[1], self.signature[2], self.signature[3]
            )
        elif self.signature[0] == "d":
            # define
            symbol_type_name = "define"
            signature_html = "#define <strong>%s</strong> %s" % (
                self.signature[1], self.signature[2]
            )
        elif self.signature[0] == "s":
            # struct
            symbol_type_name = "structure"
            signature_html = "struct <strong>%s</strong> {...}" % (
                self.signature[1]
            )

        text_html = (
            '<p style="padding: 0 0.5em">%s</p>' % "<br>".join(self.text.splitlines())
            if self.text is not None
            else ""
        )
        location = (
            "%s defined in %s" % (symbol_type_name, self.script_resref)
            if self.script_resref != "nwscript"
            else "built-in %s" % symbol_type_name
        )

        return """
        <html style="padding: 0"><body style="margin: 0">
            <div style="background-color: color(var(--foreground) {fix_color} alpha(0.07)); padding: 0.5em;">
                {signature_html}
                <div style="padding-left: 1em; color: color(var(--foreground) alpha(0.5));"><em>{location}</em></div>
            </div>
            {fix_html}
            {text_html}
        </body></html>
        """.format(
            self=self,
            fix_html=fix_html,
            fix_color="blend(%s 25%%)" % fix_color if fix_color is not None else "",
            text_html=text_html,
            location=location,
            signature_html=signature_html,
        )


class NWScriptCompletion(sublime_plugin.EventListener):
    settings = None

    def __init__(self):
        super().__init__()

        # script resref => SymbolCompletions
        self.symbol_completions = {}

        # directory => set() of include-only files
        self.include_completions = None

    def on_query_completions(self, view: sublime.View, prefix: str, locations: (str, str, (int, int))) -> list:
        if not view.scope_name(locations[0]).startswith("source.nss"):
            return

        position = locations[0]
        position = position - len(prefix)
        if (view.substr(position) != '.'):
            position = locations[0]

        module_path, file_path = self.get_opened_file_paths(view)
        file_data = view.substr(sublime.Region(0, view.size()))

        include_errors = self.parse_script_tree(module_path, file_path, file_data)

        # Handle #include completions
        row, col = view.rowcol(position)
        line = view.substr(sublime.Region(view.text_point(row, 0), position))

        if self.rgx_include_partial.match(line) is not None:
            return (
                self.get_include_completions(module_path),
                sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS
            )

        # Struct completion
        prev_word = self.get_previous_word(view, position)
        if prev_word is not None and view.substr(prev_word) == "struct":
            return (
                self.gather_struct_completions(self.get_resref(file_path)),
                sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS
            )

        # Show include error if looking for symbol completions
        if len(include_errors) > 0 and self.settings.get("enable_missing_include_popup") is True:
            text = "<br>".join(include_errors)
            sublime.active_window().active_view().show_popup(
                '<html style="background-color: color(var(--background) blend(red 75%));"><p>' + text + '</p></html>',
                max_width=600,
                flags=sublime.COOPERATE_WITH_AUTO_COMPLETE,
            )

        # Handle symbol completions
        return self.gather_symbol_completions(self.get_resref(file_path))

    def on_modified(self, view: sublime.View) -> None:
        point = view.sel()[0].begin()
        if not view.scope_name(point).startswith("source.nss"):
            return

        if self.settings.get("enable_doc_popup") is False:
            return

        module_path, file_path = self.get_opened_file_paths(view)
        file_data = view.substr(sublime.Region(0, view.size()))

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

        module_path, file_path = self.get_opened_file_paths(view)
        file_data = view.substr(sublime.Region(0, view.size()))

        self.parse_script_tree(module_path, file_path, file_data)

        self.show_doc_popup_for(
            view,
            resref=self.get_resref(file_path),
            symbol=symbol,
        )


    @staticmethod
    def get_opened_file_paths(view: sublime.View) -> (str, str):
        file_path = view.file_name()
        module_path = None
        if file_path is None:
            file_path = "__unsaved_%d.nss" % view.id()
            opened_folders = view.window().folders()
            if len(opened_folders) > 0:
                module_path = opened_folders[0]
        else:
            module_path = os.path.dirname(file_path)

        return (module_path, file_path)


    @staticmethod
    def get_resref(file_path: str) -> str:
        return os.path.splitext(os.path.basename(file_path))[0]


    @staticmethod
    def get_previous_word(view: sublime.View, point) -> sublime.Region:
        i = view.word(point).begin() - 1

        while i > 0 and view.substr(i).isspace():
            i -= 1

        return view.word(i)

    def show_doc_popup_for(self, view, resref, symbol) -> bool:
        doc = self.get_documentation(resref, symbol)
        if doc is not None:
            view.show_popup(
                doc.format_popup(),
                location=-1, max_width=view.em_width() * 80, flags=sublime.COOPERATE_WITH_AUTO_COMPLETE
            )
            return True

        if view.is_popup_visible():
            view.hide_popup()
        return False

    def get_documentation(self, resref: str, symbol: str) -> Documentation:
        explored_resrefs = set()

        def recurr_get_documentation(curr_resref) -> Documentation:
            if curr_resref not in self.symbol_completions:
                return None
            compl = self.symbol_completions[curr_resref]

            if symbol in compl.symbol_list:
                return compl.documentation[compl.symbol_list[symbol]]

            if symbol in compl.structs_doc:
                return compl.structs_doc[symbol]

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
                if dep not in explored_resrefs and dep in self.symbol_completions:
                    explored_resrefs.add(dep)
                    recurr_gather_symbol_completions(dep)

        explored_resrefs.add(resref)
        recurr_gather_symbol_completions(resref)
        return ret

    def gather_struct_completions(self, resref: str) -> list:
        ret = []
        explored_resrefs = set()

        def recurr_gather_symbol_completions(curr_resref):
            compl = self.symbol_completions[curr_resref]
            ret.extend([["%s\tstruct" % s, s] for s in compl.structs])

            for dep in compl.dependencies:
                if dep not in explored_resrefs:
                    explored_resrefs.add(dep)
                    recurr_gather_symbol_completions(dep)

        explored_resrefs.add(resref)
        recurr_gather_symbol_completions(resref)
        return ret

    # Search through include dirs and module path to find a file matching resref
    def find_file_by_resref(self, module_path: str, resref: str) -> str:
        path_list = []
        if module_path is not None:
            path_list.append(module_path)
        path_list.extend(self.settings.get("include_path"))

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
    # Returns a list of include errors
    def parse_script_tree(self, module_path: str, file_path: str, file_data: str = None) -> []:
        if self.include_completions is None:
            self.init_include_list(module_path)

        explored_resrefs = set("nwscript")
        if "nwscript" not in self.symbol_completions:
            self.parse_script(self.find_file_by_resref(module_path, "nwscript"))

        include_errors = []

        def recurr_parse(file, do_not_parse=False):
            resref = self.get_resref(file)
            compl = self.symbol_completions.get(resref, None)

            if do_not_parse is False and (compl is None or os.path.getmtime(file) > compl.mtime):
                resref, compl = self.parse_script(file)

            for dep in compl.dependencies:
                if dep not in explored_resrefs:
                    explored_resrefs.add(dep)
                    dep_file = self.find_file_by_resref(module_path, dep)
                    if dep_file is not None:
                        recurr_parse(dep_file)
                    else:
                        include_errors.append("Cannot find script '%s' (included in '%s')" % (dep, resref))

        start_resref = self.get_resref(file_path)
        explored_resrefs.add(start_resref)
        if file_data is not None:
            self.parse_script(file_path, file_data)
            recurr_parse(file_path, do_not_parse=True)
        else:
            recurr_parse(file_path)

        return include_errors


    # Parse a single script and extract completion info
    def parse_script(self, file_path: str, file_data: str = None) -> None:
        if file_data is None:
            file_data = open(file_path, encoding="utf-8", errors="ignore").read()
            file_mtime = os.path.getmtime(file_path)
        else:
            file_mtime = time.time()

        compl = SymbolCompletions()
        compl.file = file_path
        compl.mtime = file_mtime
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
                    doc.signature = ("f", fun_type, fun_name, fun_args)
                    doc.script_resref = resref
                    doc.fix = self.settings.get("doc_fixes").get(resref, {}).get(fun_name, None)
                    if doc.fix is None:
                        doc.fix = get_doc_fix(resref, fun_name)

                    doc.text = (
                        "\n".join([line[2:] for line in fun_doc.splitlines()])
                        if fun_doc != "" and not fun_doc.isspace()
                        else None
                    )
                    compl.documentation.append(doc)
                else:
                    # Set documentation if none
                    existing_index = compl.symbol_list[fun_name]
                    existing_doc = compl.documentation[existing_index]
                    if existing_doc.text is None:
                        existing_doc.text = fun_doc if fun_doc != "" and not fun_args.isspace() else None

        # const completions
        glob_rgx = self.rgx_global_nwscript if resref == "nwscript" else self.rgx_global_const
        for (glob_type, glob_name, glob_value, glob_doc) in glob_rgx.findall(file_data):
            compl.symbol_list[glob_name] = len(compl.completions)
            compl.completions.append([glob_name + "\t" + glob_type + "=" + glob_value, glob_name])
            doc = Documentation()
            doc.signature = ("c", glob_type, glob_name, glob_value)
            doc.script_resref = resref
            doc.text = glob_doc
            compl.documentation.append(doc)

        # #define completions
        for (def_name, def_value) in self.rgx_fun_define.findall(file_data):
            compl.symbol_list[def_name] = len(compl.completions)
            compl.completions.append([def_name + "\t" + def_value, def_name])
            doc = Documentation()
            doc.signature = ("d", def_name, def_value)
            doc.script_resref = resref
            compl.documentation.append(doc)

        # struct completions
        for (struct_doc, struct_name) in self.rgx_struct.findall(file_data):
            compl.structs.append(struct_name)
            doc = Documentation()
            doc.signature = ("s", struct_name)
            doc.script_resref = resref
            doc.text = (
                "\n".join([line[2:] for line in struct_doc.splitlines()])
                if struct_doc != "" and not struct_doc.isspace()
                else None
            )
            compl.structs_doc[struct_name] = doc

        # update include completions
        if self.include_completions is not None:
            file_dir = os.path.dirname(file_path)
            if file_dir in self.include_completions:
                if has_main:
                    self.include_completions[file_dir].add(resref)
                else:
                    self.include_completions[file_dir].discard(resref)

        self.symbol_completions[resref] = compl
        return (resref, compl)


    def init_include_list(self, module_path):
        if self.include_completions is not None and module_path in self.include_completions:
            return

        sublime.active_window().status_message("Building #include completions...")

        def worker():
            self.include_completions = {}

            path_list = []
            if module_path is not None:
                path_list.append(module_path)
            path_list.extend(self.settings.get("include_path"))

            for dir_path in path_list:
                # Don't go through already parsed folders
                if dir_path in self.include_completions:
                    continue

                self.include_completions[dir_path] = set()

                for file_name in os.listdir(dir_path):
                    if os.path.splitext(file_name)[1].lower() != ".nss":
                        continue
                    file_path = os.path.join(dir_path, file_name)
                    if not os.path.isfile(file_path):
                        continue

                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        data = f.read()
                        data = self.rgx_comment.sub("", data)
                        has_main = self.rgx_main.search(data) is not None

                        if not has_main:
                            self.include_completions[dir_path].add(os.path.splitext(file_name)[0])

            sublime.active_window().status_message("Building #include completions... Done !")

        threading.Thread(
            target=worker,
            args=()
        ).start()

    def get_include_completions(self, module_path):
        self.init_include_list(module_path)

        path_list = []
        if module_path is not None:
            path_list.append(module_path)
        path_list.extend(self.settings.get("include_path"))

        ret = []
        for path in path_list:
            mark = "⋄" if path is module_path else ""
            if path in self.include_completions:
                ret.extend([
                    ["%s\t%sscript" % (resref, mark), resref]
                    for resref in self.include_completions[path]
                    if resref != "nwscript"
                ])
        return ret


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
        r'\s*=\s*(.+?)\s*;(?:\s*//\s*(.*?)$)?',
        re.DOTALL | re.MULTILINE)
    rgx_global_nwscript = re.compile(
        r'^\s*' + nwn_types + r'\s+'
        r'(\w+)'
        r'\s*=\s*(.+?)\s*;(?:\s*//\s*(.*?)$)?',
        re.DOTALL | re.MULTILINE)

    rgx_struct = re.compile(r'((?:^[ \t]*//[^\n]*?\n)*)^[ \t]*struct\s+(\w+)\s*\{', re.DOTALL | re.MULTILINE)

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
