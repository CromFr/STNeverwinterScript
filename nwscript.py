import sublime, sublime_plugin
import os
import json
import sys
import functools
import re

plugin_settings = None
def read_settings(key, default):
	global plugin_settings
	if plugin_settings is None:
		plugin_settings = sublime.load_settings('nwscript.sublime-settings')

	return sublime.active_window().active_view().settings().get(key, plugin_settings.get(key, default))

def read_all_settings(key):
	global plugin_settings
	if plugin_settings is None:
		plugin_settings = sublime.load_settings('nwscript.sublime-settings')

	result = plugin_settings.get(key, [])
	result.extend(sublime.active_window().active_view().settings().get(key, []))
	return result

completions = {}


class NWScriptCompletion(sublime_plugin.EventListener):
	def on_query_completions(self, view, prefix, locations):
		if not view.scope_name(locations[0]).startswith('source.nss'):
			return

		position = locations[0]
		position = position - len(prefix)
		if (view.substr(position) != '.'):
			position = locations[0]

		response = self.request_completions(view.file_name(), view.substr(sublime.Region(0, view.size())), position)
		return (response, 0)
		# sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS

	_explored_resref = {}
	_cpl = []
	def request_completions(self, file, file_data, position):
		folder = os.path.normpath(file+"/..")
		resref = os.path.splitext(os.path.basename(file))[0];

		self._cpl = []
		self._explored_resref = {}
		self._request_completions_recurr(folder, resref)
		return self._cpl

	def _request_completions_recurr(self, folder, file_resref):
		if file_resref in self._explored_resref:
			return []
		self._explored_resref[file_resref] = 1

		if not file_resref in completions:
			file_path = self.get_file_path_by_resref(folder, file_resref)
			if file_path != None:
				file_data = ""
				try: file_data = open(file_path).read()
				except Exception as e:
					try: file_data = open(file_path, encoding="utf-8").read()
					except Exception as e: pass

				file_deps = self.get_dependencies(file_data)
				file_cpl = self.get_completions(file_resref, file_data)
				completions[file_resref] = [file_path, file_deps, file_cpl]

		self._cpl += completions[file_resref][2]

		for dep_resref in completions[file_resref][1]:
			self._request_completions_recurr(folder, dep_resref)



	def get_file_path_by_resref(self, folder, resref):
		path_list = read_all_settings("path") + [folder]
		for path in path_list:
			file = os.path.join(path, resref+".nss")
			if os.path.isfile(file):
				return file

		print("nwscript-completion: could not find '"+resref+"' in ",path_list)
		return None

	def get_dependencies(self, file_data):
		matches = self.rgx_include.findall(file_data)
		return matches + ["nwscript"]

	def get_completions(self, file_resref, file_data):
		cpl = []

		custom = ""
		if file_resref != "nwscript":
			custom = "*"

		matches = None
		if file_resref == "nwscript":
			matches = self.rgx_fun_decl.findall(file_data)
		else:
			matches = self.rgx_fun_impl.findall(file_data)

		for match in matches:
			if match[1] != "main" and match[1] != "StartingConditional":
				args = []
				i = 0
				if match[2] != "" and not match[2].isspace():
					for arg in match[2].split(","):
						arg_match_obj = self.rgx_fun_arg.search(arg);
						if arg_match_obj == None:
							print("nwscript-completion: Could not parse argument '"+arg+"' in "+file_resref+"."+match[1]);
							arg_match_obj = None
						else:
							arg_match = arg_match_obj.groups()
							default = ""
							if arg_match[2] != None:
								default += "="+arg_match[2]
							args += ["${"+str(i+1)+":/*"+arg_match[0]+" "+arg_match[1]+default+"*/}"]
						i = i+1

				# print(args)

				cpl += [[match[1]+"()"+custom+"\t"+match[0], match[1]+"("+(", ".join(args))+")"]]

		if file_resref == "nwscript":
			for match in self.rgx_global_nwscript.findall(file_data):
				cpl += [[match[1]+"\t"+match[0]+"="+match[2], match[1]]]
		else:
			for match in self.rgx_global_const.findall(file_data):
				cpl += [[match[1]+custom+"\t"+match[0]+"="+match[2], match[1]]]

		return cpl

	nwn_types = r'(void|string|int|float|object|vector|location|effect|event|talent|itemproperty|action|struct\s+\w+)'
	rgx_fun_impl = re.compile(
		nwn_types+r'\s+'
		r'(\w+)\s*'
		r'\(([^)]*?)\)\s*\{',
		re.DOTALL)
	rgx_fun_decl = re.compile(
		nwn_types+r'\s+'
		r'(\w+)\s*'
		r'\(([^)]*?)\)\s*;',
		re.DOTALL)

	rgx_fun_arg = re.compile(
		nwn_types+r'\s+'
		r'(\w+)'
		r'(?:\s*=\s*([\w."]+))?',
		re.DOTALL)

	rgx_global_const = re.compile(
		r'(?:const\s+)'
		+nwn_types+r'\s+'
		r'(\w+)'
		r'\s*=\s*([\w."]+)\s*;',
		re.DOTALL)
	rgx_global_nwscript = re.compile(
		nwn_types+r'\s+'
		r'(\w+)'
		r'\s*=\s*([\w."]+)\s*;',
		re.DOTALL)

	rgx_include = re.compile(
		r'#include\s+"([\w-]+)"',
		re.DOTALL)
