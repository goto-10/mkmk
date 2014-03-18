# Copyright 2013 the Neutrino authors (see AUTHORS).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


# Tools for building C code.


from abc import ABCMeta, abstractmethod
import os.path
from ..command import Command, shell_escape
from .. import extend
from .. import node
import re

_VALGRIND_COMMAND = [
  "valgrind", "-q", "--leak-check=full", "--error-exitcode=1"
]

_TIME_COMMAND = [
  "/usr/bin/time", "-f", "[Time: E%E U%U S%S]"
]


# A toolchain is a set of tools used to build objects, executables, etc.
class Toolchain(object):
  __metaclass__ = ABCMeta

  def __init__(self, config):
    self.config = config

  # Look ma, gcc and msvc are sharing code!
  def get_print_env_command(self):
    command = "echo CFLAGS: %s" % (" ".join(self.get_config_flags()))
    return Command(command)

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
  def get_executable_compile_command(self, output, inputs):
    pass


# The gcc toolchain. Clang is gcc-compatible so this works for clang too.
class Gcc(Toolchain):

  def get_config_flags(self):
    result = [
      "-Wall",
      "-Wextra",                    # More errors please.
      "-Wno-unused-parameter",      # Sometime you don't need all the params.
      "-Wno-unused-function",       # Not all header functions are used in all.
                                    #   the files that include them.
      "-std=c99",
    ]
    # Annoyingly this warning option only exists in gcc > 4.8 and not in clang.
    if self.config.gcc48:
      result += ["-Wno-unused-local-typedefs"]
    # Debug flags
    if self.config.debug:
      result += ["-O0", "-g"]
    else:
      result += ["-O3"]
    # Profiling
    if self.config.gprof:
      result += ["-pg"]
    # Checks en/dis-abled
    if self.config.checks:
      result += ["-DENABLE_CHECKS=1"]
    if self.config.expchecks:
      result += ["-DEXPENSIVE_CHECKS=1"]
    # Strict errors
    if not self.config.warn:
      result += ["-Werror"]
    return result

  def get_linker_flags(self):
    result = [
      "-rdynamic",
      "-lrt"
    ]
    if self.config.gprof:
      result += ["-pg"]
    return result

  def get_object_compile_command(self, output, inputs, includepaths):
    cflags = ["$(CFLAGS)"] + self.get_config_flags()
    for path in includepaths:
      cflags.append("-I%s" % shell_escape(path))
    command = "$(CC) %(cflags)s -c -o %(output)s %(inputs)s" % {
      "output": shell_escape(output),
      "inputs": " ".join(map(shell_escape, inputs)),
      "cflags": " ".join(cflags)
    }
    comment = "Building %s" % os.path.basename(output)
    return Command(command).set_comment(comment)

  def get_object_file_ext(self):
    return "o"

  def get_executable_compile_command(self, output, inputs):
    linkflags = self.get_linker_flags()
    command = "$(CC) -o %(output)s %(inputs)s %(linkflags)s" % {
      "output": shell_escape(output),
      "inputs": " ".join(map(shell_escape, inputs)),
      "linkflags": " ".join(linkflags),
    }
    comment = "Building executable %s" % os.path.basename(output)
    return Command(command).set_comment(comment)

  def get_executable_file_ext(self):
    return None


# The Microsoft visual studio toolchain.
class MSVC(Toolchain):

  def get_config_flags(self):
    result = [
      "/nologo",
      "/Wall",
      "/wd4505", # Unreferenced local function
      "/wd4514", # Unreferenced inline function
      "/wd4127", # Conditional expression is a constant
      "/wd4820", # Padding added after data member
      "/wd4800", # Forcing value to bool
      "/wd4061", # Enum not explicitly handled by case
      "/wd4365", # Conversion, signed/unsigned mismatch
      "/wd4510", # Default constructor could not be generated
      "/wd4512", # Assignment operator could not be generated
      "/wd4610", # Struct can never be instantiated
      "/wd4245", # Conversion, signed/unsigned mismatch
      "/wd4100", # Unreferenced formal parameter
      "/wd4702", # Unreachable code
      "/wd4711", # Function selected for inline expansion
      "/wd4735", # Storing 64-bit float result in memory
      "/wd4710", # Function not inlined
      "/wd4738", # Storing 32-bit float result in memory

      # Maybe look into fixing these?
      "/wd4244", # Possibly lossy conversion from int64 to int32
      "/wd4242", # Possibly lossy conversion from int32 to int8 
      "/wd4146", # Unary minus applied to unsigned
      "/wd4996", # Function may be unsafe
      "/wd4826", # Conversion is sign-extended
      "/wd4310", # Cast truncates constant
    ]
    # Debug flags
    if self.config.debug:
      result += ["/Od", "/Zi"]
    else:
      result += ["/Ox"]
    # Checks en/dis-abled
    if self.config.checks:
      result += ["/DENABLE_CHECKS=1"]
    # Strict errors
    if not self.config.warn:
      result += ["/WX"]
    return result

  def get_object_compile_command(self, output, inputs, includepaths):
    def build_source_argument(path):
      return "/Tp%s" % shell_escape(path)
    cflags = ["/c"] + self.get_config_flags()
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

  def get_executable_compile_command(self, output, inputs):
    command = "$(CC) /nologo /Fe%(output)s %(inputs)s" % {
      "output": shell_escape(output),
      "inputs": " ".join(map(shell_escape, inputs))
    }
    comment = "Building executable %s" % os.path.basename(output)
    return Command(command).set_comment(comment)

  def get_executable_file_ext(self):
    return "exe"


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


# A build dependency node that represents an executable.
class ExecutableNode(AbstractNode):

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
    inpaths = self.get_input_paths(obj=True)
    return self.get_toolchain().get_executable_compile_command(outpath, inpaths)

  def get_run_command_line(self, platform):
    flags = self.get_tools().get_custom_flags()
    exec_command = [self.get_output_file().get_path()]
    if flags.valgrind:
      exec_command = _VALGRIND_COMMAND + exec_command
    if flags.time:
      exec_command = _TIME_COMMAND + exec_command
    return " ".join(map(shell_escape, exec_command))


# A node representing a C source file.
_HEADER_PATTERN = re.compile(r'#include\s+"([^"]+)"')
class CSourceNode(AbstractNode):

  def __init__(self, name, context, tools, handle):
    super(CSourceNode, self).__init__(name, context, tools)
    self.handle = handle
    self.includes = set()
    self.headers = None

  def get_display_name(self):
    return self.handle.get_path()

  def get_input_file(self):
    return self.handle

  # Returns the list of names included into the given file. Used to calculate
  # the transitive includes.
  def get_include_names(self, handle):
    return handle.get_attribute("include names", CSourceNode.scan_for_include_names)

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
  
  # Calculates the list of handles of files included by this source file.
  def calc_included_headers(self):
    headers = set()
    files_scanned = set()
    folders = [self.handle.get_parent()] + list(self.includes)
    names_seen = set()
    # Scans the contents of the given file handle for includes, recursively
    # resolving them as they're encountered.
    def scan_file(handle):
      if (not handle.exists()) or (handle.get_path() in files_scanned):
        return
      files_scanned.add(handle.get_path())
      for name in self.get_include_names(handle):
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
    self.includes.add(path)

  # Returns a sorted list of the include paths for this source file.
  def get_includes(self):
    return sorted(list(self.includes))

  # Returns a node representing the object produced by compiling this C source
  # file.
  def get_object(self):
    name = self.get_name()
    return self.context.get_or_create_node("%s:object" % name, ObjectNode, self)


# A node representing a built object file.
class ObjectNode(AbstractNode):
  
  def __init__(self, name, context, source):
    super(ObjectNode, self).__init__(name, context, source.get_tools())
    self.add_dependency(source, src=True)
    self.source = source

  def get_source(self):
    return self.source

  def get_output_file(self):
    source_name = self.get_source().get_name()
    (source_name_root, source_name_ext) = os.path.splitext(source_name)
    ext = self.get_toolchain().get_object_file_ext()
    object_name = "%s.%s" % (source_name_root, ext)
    return self.get_context().get_outdir_file(object_name)

  def get_command_line(self, system):
    includepaths = self.source.get_includes()
    outpath = self.get_output_path()
    inpaths = self.get_input_paths(src=True)
    includes = [p.get_path() for p in includepaths]
    return self.get_toolchain().get_object_compile_command(outpath, inpaths,
      includepaths=includes)

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

  def __init__(self, controller, context):
    super(CTools, self).__init__(context)
    self.controller = controller

  # Returns the source file under the current path with the given name.
  def get_source_file(self, name):
    handle = self.context.get_file(name)
    return self.get_context().get_or_create_node(name, CSourceNode, self, handle)

  # Returns an empty executable node that can then be configured.
  def get_executable(self, name):
    return self.get_context().get_or_create_node(name, ExecutableNode, self)

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
    parser.add_argument('--time', action='store_true', default=False,
      help='Print timing information when running tests')


# Entry-point used by the framework to get the controller for the given env.
def get_controller(env):
  return CController(env)
