# Copyright 2013 the Neutrino authors (see AUTHORS).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


# Tools for building C code.


from abc import ABCMeta, abstractmethod
import hashlib
import os.path
from ..command import Command, shell_escape
from .. import extend
from .. import node
import operator
import re

_VALGRIND_COMMAND = ("valgrind", ["-q", "--leak-check=full", "--error-exitcode=1"])

_TIME_COMMAND = [
  "/usr/bin/time", "-f", "[Time: E%E U%U S%S]"
]

class Setting:

  def __init__(self, is_sticky, is_additive):
    self.values = []
    self.is_sticky = is_sticky
    self.is_additive = is_additive

  def set(self, value, restrictions):
    self.values.append((value, restrictions))

  def get(self, context, defawlt):
    assert type(context) is dict
    matches = [v for (v, r) in self.values if self.is_active(r, context)]
    if len(matches) == 0:
      return defawlt
    else:
      if self.is_additive:
        return reduce(operator.add, matches, [])
      else:
        assert len(matches) == 1
        return matches[0]

  def is_active(self, restriction, context):
    for (tag, value) in restriction.items():
      if tag in context and context[tag] != value:
        return False
    return True


class Settings:

  MODE_LOCAL = "local"
  MODE_STICKY = "sticky"
  MODE_PERVASIVE = "pervasive"

  def __init__(self, parent=None, is_pervasive=False):
    self.attribs = {}
    self.parent = parent
    self.is_pervasive = is_pervasive

  def get(self, name, context, defawlt=None, only_sticky=False):
    attrib = self.attribs.get(name, None)
    if (attrib is None) or (only_sticky and not attrib.is_sticky):
      if self.parent is None:
        return defawlt
      else:
        return self.parent.get(name, context, defawlt, True)
    elif attrib.is_additive and (not self.parent is None):
      return attrib.get(context, []) + self.parent.get(name, context, defawlt, True)
    else:
      return attrib.get(context, defawlt)

  def set_local(self, name, value, **restrictions):
    self.set(name, value, self.MODE_LOCAL, False, restrictions)

  def set_sticky(self, name, value, **restrictions):
    self.set(name, value, self.MODE_STICKY, False, restrictions)

  def set_pervasive(self, name, value, **restrictions):
    self.set(name, value, self.MODE_PERVASIVE, False, restrictions)

  def add_local(self, name, *values, **restrictions):
    self.set(name, list(values), self.MODE_LOCAL, True, restrictions)

  def add_sticky(self, name, *values, **restrictions):
    self.set(name, list(values), self.MODE_STICKY, True, restrictions)

  def add_pervasive(self, name, *values, **restrictions):
    self.set(name, list(values), self.MODE_PERVASIVE, True, restrictions)

  def set(self, name, value, mode, is_additive, restrictions):
    if (mode == self.MODE_PERVASIVE) and (not self.is_pervasive):
      return self.parent.set(name, value, mode, is_additive, restrictions)
    else:
      setting = self.attribs.get(name, None)
      is_sticky = not (mode == self.MODE_LOCAL)
      if setting is None:
        setting = Setting(is_sticky, is_additive)
        self.attribs[name] = setting
      assert (setting.is_additive == is_additive)
      assert (setting.is_sticky == is_sticky)
      setting.set(value, restrictions)


# A toolchain is a set of tools used to build objects, executables, etc.
class Toolchain(object):
  __metaclass__ = ABCMeta

  def __init__(self, config):
    self.config = config

  def use_debug_codegen(self):
    return ((self.config.debug_codegen == "on")
      or (self.config.debug_codegen == "auto" and self.config.debug))

  # Look ma, gcc and msvc are sharing code!
  def get_print_env_command(self):
    command = "echo CFLAGS: %s" % (" ".join(self.get_config_flags()))
    return Command(command)

  # Given a list of string file paths returns a file id for them.
  def get_fileid(self, inputs):
    m = hashlib.md5()
    for name in inputs:
      basename = os.path.basename(name)
      m.update(basename)
    digits = m.hexdigest()[-4:]
    return "0x%s" % digits

  def get_defines(self, inputs, settings, context):
    result = []
    if self.use_debug_codegen():
      result += self.format_define_flag("DEBUG_CODEGEN", "1")
    if self.config.checks:
      result += self.format_define_flag("ENABLE_CHECKS", "1")
    if self.config.expchecks:
      result += self.format_define_flag("EXPENSIVE_CHECKS", "1")
    if self.config.fail_on_devutils:
      result += self.format_define_flag("FAIL_ON_DEVUTILS", "1")
    if settings.get("gen_fileid", context, False):
      fileid = self.get_fileid(inputs)
      result += self.format_define_flag("FILE_ID", fileid)
      if self.config.dump_file_ids:
        # This is kind of a hack but it's probably not worth spending a huge
        # amount of time one so it should be good enough.
        print "%s: %s" % (fileid, ", ".join(inputs))
    return result

  # Returns the command for compiling a source file into an object.
  @abstractmethod
  def get_object_compile_command(self, output, inputs, includepaths):
    pass

    # Returns the file extension to use for generated object files.
  @abstractmethod
  def get_object_file_ext(self):
    pass

  # Returns the command for compiling a set of object files into an executable.
  @abstractmethod
  def get_executable_compile_command(self, output, inputs, libs):
    pass


# The gcc toolchain. Clang is gcc-compatible so this works for clang too.
class Gcc(Toolchain):

  SETTINGS_CONTEXT = {"toolchain": "msvc", "language": "c++"}

  def get_settings_context(self, is_cpp):
    result = {"toolchain": "gcc"}
    if not is_cpp is None:
      result["language"] = "c++" if is_cpp else "c"
    return result

  def format_define_flag(self, key, value):
    return ["-D%s=%s" % (key, value)]

  def get_config_flags(self, inputs, is_cpp, settings):
    context = self.get_settings_context(is_cpp)
    result = settings.get("cflags", context, [])
    result += ["-W%s" % w for w in settings.get("warnings", context, [])]
    # Annoyingly this warning option only exists in gcc > 4.8 and not in clang.
    if self.config.gcc48:
      result += ["-Wno-unused-local-typedefs"]
    optflag = "-O3"
    # Debug flags
    if self.config.debug:
      result += ["-g"]
      if self.config.gcc48:
        # This one is new in gcc48 but is made to be used with -g
        optflag = "-Og"
      else:
        # Otherwise we'll err on the side of performance, -O0 is just too slow
        # especially when used with valgrind.
        optflag = "-O1"
    if self.config.fastcompile:
      # Fastcompile overrides everything.
      optflag = "-O0"
    result += self.get_defines(inputs, settings, context)
    result += [optflag]
    # Profiling
    if self.config.gprof:
      result += ["-pg"]
    # Strict errors
    if not self.config.warn:
      result += ["-Werror"]
    return result

  def get_base_linker_flags(self, settings):
    context = self.get_settings_context(None)
    result = settings.get("linkflags", context, [])
    result = [
      "-rdynamic",
      "-lstdc++",
    ]
    if self.config.gprof:
      result += ["-pg"]
    return result

  # Returns the set of linker flags to pass when linking, given a list of the
  # libraries to link with.
  def get_linker_flags(self, settings, libs):
    return self.get_base_linker_flags(settings) + ["-l%s" % lib for lib in libs]

  def get_object_compile_command(self, output, inputs, includepaths, defines,
      is_cpp, force_c, settings):
    cflags = ["$(CFLAGS)"] + self.get_config_flags(inputs, is_cpp, settings)
    for path in includepaths:
      cflags.append("-I%s" % shell_escape(path))
    if is_cpp:
      compiler = "$(CXX)"
    else:
      compiler = "$(CC)"
    for (name, value) in defines:
      cflags.append("-D%s=%s" % (name, value))
    command = "%(compiler)s %(cflags)s -c -o %(output)s %(inputs)s" % {
      "compiler": compiler,
      "output": shell_escape(output),
      "inputs": " ".join(map(shell_escape, inputs)),
      "cflags": " ".join(cflags)
    }
    comment = "Building %s" % os.path.basename(output)
    return Command(command).set_comment(comment)

  def get_object_file_ext(self):
    return "o"

  def get_executable_compile_command(self, output, inputs, libs, settings):
    linkflags = self.get_linker_flags(settings, libs)
    command = "$(CC) -o %(output)s  -Wl,--start-group %(inputs)s -Wl,--end-group %(linkflags)s" % {
      "output": shell_escape(output),
      "inputs": " ".join(map(shell_escape, inputs)),
      "linkflags": " ".join(linkflags),
    }
    comment = "Building executable %s" % os.path.basename(output)
    return Command(command).set_comment(comment)

  def get_shared_library_compile_command(self, output, inputs, libs, settings):
    linkflags = self.get_linker_flags(settings, libs)
    command = "$(CC) -shared -o %(output)s %(inputs)s %(linkflags)s" % {
      "output": shell_escape(output),
      "inputs": " ".join(map(shell_escape, inputs)),
      "linkflags": " ".join(linkflags),
    }
    comment = "Building shared library %s" % os.path.basename(output)
    return Command(command).set_comment(comment)

  def get_message_resource_compile_command(self, output, inputs):
    command = "touch %s" % output
    comment = "Creating dummy message resource %s" % os.path.basename(output)
    return Command(command).set_comment(comment)

  def get_executable_file_ext(self):
    return None

  def get_shared_library_file_ext(self):
    return "so"

  def get_message_resource_file_ext(self):
    return None


# The Microsoft visual studio toolchain.
class MSVC(Toolchain):

  SETTINGS_CONTEXT = {"toolchain": "msvc", "language": "c++"}

  def get_settings_context(self):
    return MSVC.SETTINGS_CONTEXT

  def format_define_flag(self, key, value):
    return ["/D%s=%s" % (key, value)]

  def get_config_flags(self, inputs, settings):
    context = self.get_settings_context()
    result = settings.get("cflags", context, [])
    result += ["/Wall"]
    result += ["/w%s" % w for w in settings.get("warnings", context, [])]
    # Debug flags
    if self.config.debug:
      result += ["/Od"]
    else:
      result += ["/Ox"]
    if self.use_debug_codegen():
      result += ["/Zi"]
    result += self.get_defines(inputs, settings, context)
    # Strict errors
    if not self.config.warn:
      result += ["/WX"]
    return result

  def get_object_compile_command(self, output, inputs, includepaths, defines,
      is_cpp, force_c, settings):
    def build_source_argument(path):
      # Unless you explicitly force C compilation we'll use C++ even for C
      # files because the version of C supported by MSVC is ancient.
      if force_c:
        option = "Tc"
      else:
        option = "Tp"
      return "/%s%s" % (option, shell_escape(path))
    cflags = ["/c"] + self.get_config_flags(inputs, settings)
    if self.config.debug:
      cflags += ["/Fd%s.pdb" % shell_escape(output)]
    for path in includepaths:
      cflags.append("/I%s" % shell_escape(path))
    command = "$(CC) %(cflags)s /Fo%(output)s %(inputs)s" % {
      "output": shell_escape(output),
      "inputs": " ".join(map(build_source_argument, inputs)),
      "cflags": " ".join(cflags)
    }
    comment = "Building %s" % os.path.basename(output)
    return Command(command).set_comment(comment)

  def get_object_file_ext(self):
    return "obj"

  def get_executable_compile_command(self, output, inputs, libs, settings):
    cflags = settings.get("linkflags", self.get_settings_context(), [])
    if self.use_debug_codegen():
      cflags += ["/DEBUG"]
    if self.config.debug:
      cflags += ["/PDB:%s.pdb" % shell_escape(output)]
    subsystem = settings.get("subsystem", self.get_settings_context())
    if not subsystem is None:
      cflags += ["/SUBSYSTEM:%s" % subsystem]
    cflags += settings.get("compiler-flags", self.get_settings_context(), [])
    command = "link %(cflags)s /OUT:%(output)s %(inputs)s" % {
      "output": shell_escape(output),
      "inputs": " ".join(map(shell_escape, inputs + libs)),
      "cflags": " ".join(cflags)
    }
    comment = "Building executable %s" % os.path.basename(output)
    return Command(command).set_comment(comment)

  def get_shared_library_compile_command(self, output, inputs, libs, settings):
    cflags = ["/NOLOGO", "/DLL"]
    if self.use_debug_codegen:
      cflags += ["/DEBUG"]
    command = "link.exe %(cflags)s /OUT:%(output)s %(inputs)s" % {
      "cflags": " ".join(cflags),
      "output": shell_escape(output),
      "inputs": " ".join(map(shell_escape, inputs + libs))
    }
    comment = "Building shared library %s" % os.path.basename(output)
    return Command(command).set_comment(comment)

  def get_message_resource_compile_command(self, output, inputs):
    (base, ext) = os.path.splitext(output)
    command_1 = "mc.exe -z %(output)s %(inputs)s" % {
      "output": shell_escape(base),
      "inputs": " ".join(map(shell_escape, inputs))
    }
    command_2 = "rc.exe /nologo /r %(output)s.rc" % {
      "output": shell_escape(base)
    }
    comment = "Building message resource %s" % os.path.basename(output)
    return Command(command_1, command_2).set_comment(comment)

  def get_executable_file_ext(self):
    return "exe"

  def get_shared_library_file_ext(self):
    return "dll"

  def get_message_resource_file_ext(self):
    return "res"


# Returns the toolchain with the given name
def get_toolchain(name, config):
  if name == "gcc":
    return Gcc(config)
  elif name == "msvc":
    return MSVC(config)
  else:
    raise Exception("Unknown toolchain %s" % name)


class AbstractNode(node.PhysicalNode):
  __metaclass__ = ABCMeta

  def __init__(self, name, context, tools):
    super(AbstractNode, self).__init__(name, context)
    self.tools = tools

  # Returns the C toolset that was used to produce this node.
  def get_tools(self):
    return self.tools

  def get_toolchain(self):
    return self.get_tools().get_toolchain()

  # Returns the shared libraries required by an object in this node's set of
  # dependencies.
  def get_object_libraries(self, platform):
    all_libs = set()
    for obj in self.get_input_nodes(obj=True):
      libs = obj.get_libraries(platform)
      all_libs = all_libs.union(libs)
    return sorted(all_libs)


# A build dependency node that represents an executable.
class ExecutableNode(AbstractNode):

  def __init__(self, name, context, tools):
    super(ExecutableNode, self).__init__(name, context, tools)
    self.settings = Settings(CTools.get_settings_from_context(context))

  def get_settings(self):
    return self.settings

  def get_output_file(self):
    name = self.get_name()
    ext = self.get_toolchain().get_executable_file_ext()
    if ext:
      filename = "%s.%s" % (name, ext)
    else:
      filename = name
    return self.get_context().get_outdir_file(filename)

  # Adds an object file to be compiled into this executable. Groups will be
  # flattened.
  def add_object(self, node):
    self.add_dependency(node, obj=True)

  def get_command_line(self, platform):
    outpath = self.get_output_path()
    inpaths = sorted(set(self.get_input_paths(obj=True)))
    obj_libs = self.get_object_libraries(platform)
    return self.get_toolchain().get_executable_compile_command(outpath, inpaths,
        obj_libs, self.settings)

  def get_run_command_builder(self, platform):
    executable = self.get_output_file().get_path()
    args = []
    flags = self.get_tools().get_custom_flags()
    if flags.valgrind:
      (vexec, vargs) = _VALGRIND_COMMAND
      extra_args = ["--%s" % flag for flag in flags.valgrind_flag]
      args = vargs + extra_args + [executable]
      executable = vexec
    return platform.new_command_builder(executable, *args)


# A build dependency node that represents a shared library.
class SharedLibraryNode(AbstractNode):

  def __init__(self, name, context, tools):
    super(SharedLibraryNode, self).__init__(name, context, tools)
    self.libraries = set()
    self.settings = Settings(CTools.get_settings_from_context(context))

  def get_settings(self):
    return self.settings

  def get_output_file(self):
    name = self.get_name()
    ext = self.get_toolchain().get_shared_library_file_ext()
    if ext:
      filename = "%s.%s" % (name, ext)
    else:
      filename = name
    return self.get_context().get_outdir_file(filename)

  # Adds an object file to be compiled into this shared library. Groups will be
  # flattened.
  def add_object(self, node):
    self.add_dependency(node, obj=True)

  # Adds a file to the set of libraries to link with.
  def add_library(self, file):
    self.libraries.add(file.get_path())

  # Returns the sorted list of libraries to link with.
  def get_libraries(self, platform):
    all_libs = self.get_object_libraries(platform) + list(self.libraries)
    return sorted(list(all_libs))

  def get_command_line(self, platform):
    outpath = self.get_output_path()
    inpaths = sorted(set(self.get_input_paths(obj=True)))
    libs = self.get_libraries(platform)
    return self.get_toolchain().get_shared_library_compile_command(outpath, inpaths, libs, self.settings)


class MessageResourceNode(AbstractNode):

  def get_output_file(self):
    name = self.get_name()
    ext = self.get_toolchain().get_message_resource_file_ext()
    if ext:
      filename = "%s.%s" % (name, ext)
    else:
      filename = name
    return self.get_context().get_outdir_file(filename)

  def add_source(self, node):
    self.add_dependency(node, src=True)

  def get_command_line(self, platform):
    outpath = self.get_output_path()
    inpaths = self.get_input_paths(src=True)
    return self.get_toolchain().get_message_resource_compile_command(outpath, inpaths)

# A node representing a C source file.
_HEADER_PATTERN = re.compile(r'#\s*include\s+"([^"]+)"')
class CSourceNode(AbstractNode):

  def __init__(self, name, context, tools, handle):
    super(CSourceNode, self).__init__(name, context, tools)
    self.handle = handle
    self.local_includes = set()
    self.system_includes = set()
    self.headers = None
    self.defines = []
    self.force_c = False

  def get_display_name(self):
    return self.handle.get_path()

  def get_input_file(self):
    return self.handle

  def set_force_c(self, value):
    self.force_c = value
    return self

  def get_force_c(self):
    return self.force_c

  # Returns the list of names included into the given file. Used to calculate
  # the transitive includes.
  @staticmethod
  def get_include_names(handle):
    return handle.get_attribute("include_names",
      CSourceNode.scan_for_include_names, sticky=True)

  # Scans a file for includes. You generally don't want to call this directly
  # because it's slow, instead use get_include_names which caches the result on
  # the file handle.
  @staticmethod
  def scan_for_include_names(handle):
    result = set()
    for line in handle.read_lines():
      match = _HEADER_PATTERN.match(line)
      if match:
        name = match.group(1)
        result.add(name)
    return sorted(list(result))

  # Returns the list of headers included (including transitively) into this
  # source file.
  def get_included_headers(self):
    if self.headers is None:
      self.headers = self.calc_included_headers()
    return self.headers

  # Returns the string paths of all the includepaths.
  def get_include_paths(self):
    return [i.get_path() for i in self.get_local_includes()] + sorted(self.system_includes)

  # Gets the local files included, that is, the files that we should watch for
  # changes as opposed to system includes which are assumed to lie outside the
  # project and not change.
  def get_local_includes(self):
    result = []
    for inc in sorted(self.local_includes):
      result += inc.get_input_files()
    return sorted(result)

  # Calculates the list of handles of files included by this source file.
  def calc_included_headers(self):
    headers = set()
    files_scanned = set()
    folders = [self.handle.get_parent()] + self.get_local_includes()
    names_seen = set()
    # Scans the contents of the given file handle for includes, recursively
    # resolving them as they're encountered.
    def scan_file(handle):
      if (not handle.exists()) or (handle.get_path() in files_scanned):
        return
      files_scanned.add(handle.get_path())
      for name in CSourceNode.get_include_names(handle):
        resolve_include(name)
    # Looks for the source of a given include in the include paths and if found
    # recursively scans the file for includes.
    def resolve_include(name):
      if name in names_seen:
        return
      names_seen.add(name)
      for parent in folders:
        candidate = parent.get_child(name)
        if candidate.exists():
          if not candidate in headers:
            headers.add(candidate)
            scan_file(candidate)
          return
    scan_file(self.handle)
    return sorted(list(headers))

  # Add a folder to the include paths required by this source file. Adding the
  # same path more than once is safe.
  def add_include(self, path):
    self.local_includes.add(path)

  # Adds a string path to the list of system includes for this file.
  def add_system_include(self, path):
    assert isinstance(path, basestring)
    self.system_includes.add(path)

  def add_define(self, key, value):
    self.defines.append((key, value))

  def get_defines(self):
    return self.defines

  # Returns a node representing the object produced by compiling this C source
  # file.
  def get_object(self):
    name = self.get_name()
    is_cpp = name.endswith(".cc")
    return self.context.get_or_create_node("%s:object" % name, ObjectNode, self, is_cpp)


# A node representing a built object file.
class ObjectNode(AbstractNode):

  def __init__(self, name, context, source, is_cpp):
    super(ObjectNode, self).__init__(name, context, source.get_tools())
    self.add_dependency(source, src=True)
    self.source = source
    self.is_cpp = is_cpp
    self.libraries = set()
    self.settings = Settings(CTools.get_settings_from_context(context))

  def get_source(self):
    return self.source

  def add_library(self, lib):
    info = self.context.get_library_info(lib)
    system = self.context.get_system()
    instance = info.get_instance(system.get_os())
    instance.ensure_auto_resolved(system)
    for inc in instance.get_includes():
      self.source.add_system_include(inc)
    for lib in instance.get_libs():
      self.libraries.add(lib)

  def get_libraries(self, platform):
    return sorted(self.libraries)

  def get_output_file(self):
    source_name = self.get_source().get_name()
    ext = self.get_toolchain().get_object_file_ext()
    object_name = "%s.%s" % (source_name, ext)
    return self.get_context().get_outdir_file(object_name)

  def get_command_line(self, system):
    includes = self.source.get_include_paths()
    defines = self.source.get_defines()
    outpath = self.get_output_path()
    inpaths = self.get_input_paths(src=True)
    return self.get_toolchain().get_object_compile_command(outpath, inpaths,
      includepaths=includes, defines=defines, is_cpp=self.is_cpp,
      force_c=self.source.get_force_c(), settings=self.settings)

  def get_computed_dependencies(self):
    return self.get_source().get_included_headers()


# Node that represents the action of printing the build environment to stdout.
class EnvPrinterNode(AbstractNode):

  def __init__(self, name, context, tools):
    super(EnvPrinterNode, self).__init__(name, context, tools)

  def get_command_line(self, system):
    return self.get_tools().get_print_env_command()


# The tools for working with C. Available in mkmk files as "c".
class CTools(extend.ToolSet):

  SETTINGS_KEY = "c_settings"

  def __init__(self, controller, context):
    super(CTools, self).__init__(context)
    self.controller = controller
    self.settings = self.new_settings(context)

  def new_settings(self, context):
    parent_context = context.get_parent()
    if parent_context is None:
      parent_settings = CTools.get_or_create_settings_from_env(context)
    else:
      parent_settings = CTools.get_settings_from_context(parent_context)
    result = Settings(parent_settings)
    context.set_attribute(self.SETTINGS_KEY, result)
    return result

  @staticmethod
  def get_settings_from_context(context):
    return context.get_attribute(CTools.SETTINGS_KEY)

  @staticmethod
  def get_or_create_settings_from_env(context):
    current = context.get_pervasive_attribute(CTools.SETTINGS_KEY)
    if current is None:
      current = Settings(is_pervasive=True)
      context.set_pervasive_attribute(CTools.SETTINGS_KEY, current)
    return current

  def get_settings(self):
    return self.settings

  # Returns the source file under the current path with the given name.
  def get_source_file(self, name):
    handle = self.context.get_file(name)
    return self.get_context().get_or_create_node(name, CSourceNode, self, handle)

  # Returns an empty executable node that can then be configured.
  def get_executable(self, name):
    return self.get_context().get_or_create_node(name, ExecutableNode, self)

  # Returns an empty shared library node that can then be configured.
  def get_shared_library(self, name):
    return self.get_context().get_or_create_node(name, SharedLibraryNode, self)

  # Returns an empty message resource node that can then be configured. These
  # don't actually do anything except on windows.
  def get_message_resource(self, name):
    return self.get_context().get_or_create_node(name, MessageResourceNode, self)

  def get_env_printer(self, name):
    return self.get_context().get_or_create_node(name, EnvPrinterNode, self)

  def get_toolchain(self):
    return self.controller.get_toolchain()

  def get_custom_flags(self):
    return self.controller.get_custom_flags()


# The controller for this toolset.
class CController(extend.ToolController):

  def __init__(self, env):
    super(CController, self).__init__(env)
    self.toolchain = None

  def get_tools(self, context):
    return CTools(self, context)

  # Returns the build platform appropriate for this C build process.
  def get_toolchain(self):
    if self.toolchain is None:
      flags = self.get_custom_flags()
      self.toolchain = get_toolchain(flags.toolchain, flags)
    return self.toolchain

  def get_custom_flags(self):
    return self.get_environment().get_custom_flags()

  def add_custom_flags(self, parser):
    parser.add_argument('--debug', action='store_true', default=False,
      help='Build C objects and executables in debug mode?')
    parser.add_argument('--debug-codegen', choices=['on', 'off', 'auto'],
      default='auto', help='Generate code with debug information')
    parser.add_argument('--fail-on-devutils', action='store_true', default=False,
      help='Crash on use of development/debugging functionality?')
    parser.add_argument('--gcc48', action='store_true', default=False,
      help='Will we be building with gcc48?')
    parser.add_argument('--expchecks', action='store_true', default=False,
      help='Enable expensive runtime checks?')
    parser.add_argument('--toolchain', action='store', default='gcc',
      help='Which C toolchain to use')
    parser.add_argument('--gprof', action='store_true', default=False,
      help='Enable gprof profiling?')
    parser.add_argument('--nochecks', action='store_false', default=True,
      dest='checks', help='Execute dynamic checks?')
    parser.add_argument('--warn', action='store_true', default=False,
      help='Don\'t fail compilation on warnings')
    parser.add_argument('--valgrind', action='store_true', default=False,
      help='Run under valgrind')
    parser.add_argument('--valgrind-flag', action='append', default=[],
      help='Additional flag to pass to valgrind. A "--" will be prepended.')
    parser.add_argument('--time', action='store_true', default=False,
      help='Print timing information when running tests')
    parser.add_argument('--fastcompile', action='store_true', default=False,
      help='Compile as fast as possible, likely causing slower runtime')
    parser.add_argument('--dump-file-ids', action='store_true', default=False,
      help='During compilation, dump a mapping from files to their fat bool ids')


# Entry-point used by the framework to get the controller for the given env.
def get_controller(env):
  return CController(env)
