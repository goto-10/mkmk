# Copyright 2013 the Neutrino authors (see AUTHORS).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


# Tools for building neutrino code.


from .. import extend
from .. import node
from ..command import Command, shell_escape


# A node representing a neutrino source file.
class NSourceNode(node.PhysicalNode):

  def __init__(self, name, context, handle):
    super(NSourceNode, self).__init__(name, context)
    self.handle = handle

  def get_input_file(self):
    return self.handle


# A node representing a neutrino binary built by the python neutrino compiler.
class NBinary(node.PhysicalNode):

  # Adds a source file that should be included in this library.
  def add_source(self, node):
    self.add_dependency(node, src=True)
    return self

  # Adds a module manifest describing the module to construct.
  def add_manifest(self, node):
    self.add_dependency(node, manifest=True)
    return self

  # Sets the compiler executable to use when building this library.
  def set_compiler(self, compiler):
    self.add_dependency(compiler, compiler=True)
    return self

  def get_output_file(self):
    name = self.get_name()
    ext = self.get_output_ext()
    filename = "%s.%s" % (name, ext)
    return self.get_context().get_outdir_file(filename)


# A neutrino library
class NLibrary(NBinary):

  def get_output_ext(self):
    return "nl"

  def get_command_line(self, system):
    [compiler_node] = self.get_input_nodes(compiler=True)
    manifests = ['"%s"' % m for m in self.get_input_paths(manifest=True)]
    outpath = self.get_output_path()
    options = ["--compile", "{", "--build_library", "{", "--out", '"%s"' % outpath,
        "--modules", "["] + manifests + ["]", "}", "}"]
    return compiler_node.get_run_command_builder(system, options).build()


# A neutrino program.
class NProgram(NBinary):

  def get_output_ext(self):
    return "np"

  # Adds a module dependency that should be compiled into this program.
  def add_module(self, node):
    self.add_dependency(node, module=True)
    return self

  def get_command_line(self, system):
    [compiler_node] = self.get_input_nodes(compiler=True)
    outpath = self.get_output_path()
    [file] = self.get_input_paths(src=True)
    modules = ['"%s"' % m for m in self.get_input_paths(module=True)]
    options = (["--files[", '"%s"' % file, "]", "--compile{", "--modules["] +
        modules + ["]", "}", "--out", '"%s"' % outpath])
    return compiler_node.get_run_command_builder(system, options).build()


# The tools for working with neutrino. Available in mkmk files as "n".
class NTools(extend.ToolSet):

  # Returns the source file under the current path with the given name.
  def get_source_file(self, name):
    handle = self.context.get_file(name)
    return self.get_context().get_or_create_node(name, NSourceNode, handle)

  # Returns the module manifest file under the current path with the given name.
  def get_module_file(self, name):
    return self.get_source_file(name)

  # Returns a neutrino library file under the current path.
  def get_library(self, name):
    return self.get_context().get_or_create_node(name, NLibrary)

  # Returns a neutrino library file under the current path.
  def get_program(self, name):
    return self.get_context().get_or_create_node(name, NProgram)


class NController(extend.ToolController):

  def get_tools(self, context):
    return NTools(context)


# Entry-point used by the framework to get the controller for the given env.
def get_controller(env):
  return NController(env)
