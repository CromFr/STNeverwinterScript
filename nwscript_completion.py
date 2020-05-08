import sublime
import sublime_plugin
import os
import re
from .nwscript_doc_fixes import get_doc_fix

plugin_settings = None


def read_all_settings(key):
    global plugin_settings
    if plugin_settings is None:
        plugin_settings = sublime.load_settings('nwscript.sublime-settings')

    result = plugin_settings.get(key, [])
    result.extend(sublime.active_window().active_view().settings().get(key, []))
    return result


class FileCompletions:
    file = None
    mtime = None
    dependencies = []
    completions = []

    documentation = []
    symbol_list = {}


class NWScriptCompletion(sublime_plugin.EventListener):

    # script resref => FileCompletions
    cached_completions = {}

    def on_query_completions(self, view, prefix, locations):
        if not view.scope_name(locations[0]).startswith('source.nss'):
            return

        position = locations[0]
        position = position - len(prefix)
        if (view.substr(position) != '.'):
            position = locations[0]

        file_name = view.file_name()
        file_data = view.substr(sublime.Region(0, view.size()))
        return self.request_completions(file_name, file_data, position)

    def on_modified(self, view: sublime.View) -> None:
        if int(sublime.version()) < 3070:
            return

        point = view.sel()[0].begin()
        if not view.scope_name(point).startswith('source.nss'):
            return

        if view.substr(point) in ['(', ')'] or point != view.sel()[0].end():
            point -= 1

        func_name = view.substr(view.word(point))

        resref = os.path.splitext(os.path.basename(view.file_name()))[0]

        doc = self.find_documentation(resref, func_name, set())
        if doc is not None:
            view.show_popup(
                doc,
                location=-1, max_width=600, flags=sublime.COOPERATE_WITH_AUTO_COMPLETE
            )

    def find_documentation(self, resref, symbol, _explored_resrefs) -> str:
        if resref in _explored_resrefs:
            return
        _explored_resrefs.add(resref)

        if resref in self.cached_completions:
            file_comp = self.cached_completions[resref]

            # Search in current script
            index = file_comp.symbol_list.get(symbol, None)
            if index is not None:
                return file_comp.documentation[index]

            # Search in dependencies
            for dep in file_comp.dependencies:
                match = self.find_documentation(dep, symbol, _explored_resrefs)
                if match is not None:
                    return match

        return None

    _cpl = None

    def request_completions(self, file, file_data, position):
        folder = os.path.normpath(file + "/..")
        resref = os.path.splitext(os.path.basename(file))[0]

        self._cpl = []

        # Get completions for current file
        comp = FileCompletions()
        comp.file = file
        comp.mtime = os.path.getmtime(file)
        comp.dependencies = self.parse_script_dependencies(file_data)
        comp.completions, comp.documentation, comp.symbol_list \
            = self.parse_script_completions(resref, file_data)
        self.cached_completions[resref] = comp

        self._cpl.extend(comp.completions)

        # Add completions from dependencies
        explored_resref = set()
        for dep in comp.dependencies:
            self._request_completions_recurr(folder, dep, explored_resref)

        # Return result
        return self._cpl

    def _request_completions_recurr(self, folder, file_resref, _explored_resref=set()):
        if file_resref in _explored_resref:
            return
        _explored_resref.add(file_resref)

        file_comp = self.cached_completions.get(file_resref, None)
        if file_comp is None or os.path.getmtime(file_comp.file) > file_comp.mtime:
            file_path = self.find_file_by_resref(folder, file_resref)
            if file_path is not None:
                file_data = ""
                try:
                    file_data = open(file_path).read()
                except ValueError:
                    try:
                        file_data = open(file_path, encoding="utf-8").read()
                    except ValueError:
                        pass

                file_comp = FileCompletions()
                file_comp.file = file_path
                file_comp.mtime = os.path.getmtime(file_path)
                file_comp.dependencies = self.parse_script_dependencies(file_data)
                file_comp.completions, file_comp.documentation, file_comp.symbol_list \
                    = self.parse_script_completions(file_resref, file_data)
                self.cached_completions[file_resref] = file_comp

        self._cpl.extend(file_comp.completions)

        for dep_resref in file_comp.dependencies:
            self._request_completions_recurr(folder, dep_resref, _explored_resref)

    def find_file_by_resref(self, folder, resref):
        path_list = read_all_settings("include_path") + [folder]
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

    def parse_script_dependencies(self, file_data):
        matches = self.rgx_include.findall(file_data)
        return matches + ["nwscript"]

    def parse_script_completions(self, file_resref, file_data) -> (list, list):
        # symbol => index
        symbols = {}
        ret_cpl = []
        ret_doc = []

        file_data = self.rgx_multiline_comment.sub("", file_data)

        custom = ""
        if file_resref != "nwscript":
            custom = "⋄"

        matches = self.rgx_fun.findall(file_data)

        # Function completion
        for (fun_doc, fun_type, fun_name, fun_args) in matches:
            if fun_name not in ("main", "StartingConditional"):
                # Parse function arguments
                args_list = []
                i = 0
                if fun_args != "" and not fun_args.isspace():
                    for arg in fun_args.split(","):
                        arg_match_obj = self.rgx_fun_arg.search(arg)
                        if arg_match_obj is None:
                            print("nwscript-completion: Could not parse argument '%s' in %s.%s" % (
                                arg, file_resref, fun_name
                            ))
                            arg_match_obj = None
                        else:
                            arg_match = arg_match_obj.groups()
                            default = ""
                            if arg_match[2] is not None:
                                default += "=" + arg_match[2]
                            args_list.append("${%d:%s %s}" % (i + 1, arg_match[0], arg_match[1] + default))
                        i = i + 1

                # Format doc
                doc_fix = get_doc_fix(file_resref, fun_name)
                fun_doc = (
                    '<p><div><strong>%s %s(%s)</strong></div><div style="padding-left: 1em"><em>defined in %s</em></div></p>' % (fun_type, fun_name, fun_args, file_resref)
                    + (doc_fix if doc_fix is not None else "")
                    + (("<p>" + "<br>".join([line[2:] for line in fun_doc.splitlines()]) + "</p>") if fun_doc != "" and not fun_args.isspace() else "")
                )

                if fun_name not in symbols:
                    # Register new symbol
                    symbols[fun_name] = len(ret_cpl)
                    ret_cpl.append([
                        "%s\t%s()" % (fun_name, custom + fun_type),
                        "%s(%s)" % (fun_name, ", ".join(args_list))
                    ])
                    ret_doc.append(fun_doc)
                else:
                    # Set documentation if none
                    existing_index = symbols[fun_name]
                    if ret_doc[existing_index] is None:
                        ret_doc[existing_index] = fun_doc

        # const completions
        glob_rgx = self.rgx_global_nwscript if file_resref == "nwscript" else self.rgx_global_const
        for (glob_type, glob_name, glob_value) in glob_rgx.findall(file_data):
            ret_cpl.append([glob_name + "\t" + glob_type + "=" + glob_value, glob_name])
            ret_doc.append("")

        # #define completions
        for (def_name, def_value) in self.rgx_fun_define.findall(file_data):
            ret_cpl.append([def_name + "\t" + def_value, def_name])
            ret_doc.append("")

        return (ret_cpl, ret_doc, symbols)

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

    rgx_multiline_comment = re.compile(r'/\*.*?\*/', re.DOTALL)
