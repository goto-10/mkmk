#!/usr/bin/python
#- Copyright 2014 GOTO 10.
#- Licensed under the Apache License, Version 2.0 (see LICENSE).

from command import Command, shell_escape
import argparse
import node
import os
import os.path
import re
import sys


## Implements the 'makefile' command.


# An individual target within a makefile.
class MakefileTarget(object):

  def __init__(self, output, inputs, commands):
    self.output = output
    self.inputs = inputs
    self.commands = commands

  # Returns the string output path for this target.
  def get_output_path(self):
    return self.output

  # Write this target, in Makefile syntax, to the given output stream.
  def write(self, out):
    out.write("%(outpath)s: %(inpaths)s\n\t%(commands)s\n\n" % {
      "outpath": shell_escape(self.output),
      "inpaths": " ".join(map(shell_escape, self.inputs)),
      "commands": "\n\t".join(self.commands)
    })


# The contents of a complete makefile. A makefile object is meant to be dumb and
# basically only concerned with accumulating and then printing the makefile
# source. Any nontrivial logic is the responsibility of whoever is building the
# makefile object.
class Makefile(object):

  def __init__(self):
    self.targets = {}
    self.phonies = set()

  # Add a target that builds the given output from the given inputs by invoking
  # the given commands in sequence.
  def add_target(self, output, inputs, commands, is_phony):
    target = MakefileTarget(output, inputs, commands)
    self.targets[output] = target
    if is_phony:
      self.phonies.add(output)

  # Write this makefile in Makefile syntax to the given stream.
  def write(self, out):
    for name in sorted(self.targets.keys()):
      target = self.targets[name]
      target.write(out)
    # Mike Moffit says: list *all* the phonies.
    if self.phonies:
      out.write(".PHONY: %s\n\n" % " ".join(sorted(list(self.phonies))))


# A segmented name. This is sort of like a relative file path but avoids any
# ambiguities that might be caused by multiple relative paths pointing to the
# same thing and differences in path separators etc. Names compare
# lexicographically and are equal if their parts are structurally equal.
class Name(object):

  def __init__(self, parts):
    self.parts = tuple(parts)

  # Returns a new name that consists of this name followed by the given parts.
  def append(self, *subparts):
    return Name(self.parts + subparts)

  # Returns a new name that consists of the given prefix followed by this name.
  def prepend(self, *prefix):
    return Name(prefix + self.parts)

  # Returns a tuple that holds the parts of this name.
  def get_parts(self):
    return self.parts

  # Returns the last part, for instance the last part of a|b|c is "c".
  def get_last_part(self):
    return self.parts[-1]

  @staticmethod
  def of(*parts):
    return Name(parts)

  def __hash__(self):
    return ~hash(self.parts)

  def __eq__(self, that):
    return (self.parts == that.parts)

  def __cmp__(self, that):
    return cmp(self.parts, that.parts)

  def __str__(self):
    return "::".join(self.parts)

  def __repr__(self):
    return str(self)


# An abstract file wrapper that encapsulates various file operations.
class AbstractFile(object):

  def __init__(self, path, parent):
    self.path = path
    self.parent = parent
    self.children = {}
    self.attribs = {}

  # Creates a new file object of the appropriate type depending on what kind of
  # file the path points to.
  @staticmethod
  def at(path, parent=None):
    if os.path.isdir(path):
      return Folder(path, parent)
    elif os.path.isfile(path):
      return RegularFile(path, parent)
    else:
      return MissingFile(path, parent)

  # Returns the folder that contains this file.
  def get_parent(self):
    if self.parent is None:
      self.parent = AbstractFile.at(os.path.dirname(self.path))
    return self.parent

  # Returns a file representing the child under this folder with the given path.
  def get_child(self, *child_path):
    current = self
    for part in child_path:
      current = current.get_local_child(part)
    return current

  # Like get_child but only takes a single argument so only files directly under
  # this folder can be accessed this way.
  def get_local_child(self, part):
    if not part in self.children:
      child = AbstractFile.at(os.path.join(self.path, part), parent=self)
      self.children[part] = child
    return self.children[part]

  # Returns the raw underlying (relative) string path.
  def get_path(self):
    return self.path

  # Is this file handle backed by a physical file?
  def exists(self):
    return os.path.exists(self.get_path())

  # Returns an in-memory attribute associated with this file, computing it using
  # the given thunk if it doesn't already exist.
  def get_attribute(self, name, thunk):
    if not name in self.attribs:
      self.attribs[name] = thunk(self)
    return self.attribs[name]

  def __cmp__(self, that):
    return cmp(self.path, that.path)

  # There has to be two comparison functions because cmp doesn't work in python
  # 3.
  #
  # Python 3: out users' time is cheap so why make an effort to be compatible?
  def __lt__(self, that):
    return self.path < that.path


# A wrapper that represents a file that doesn't exist yet. Using files that
# don't exist is fine but if you try to interact with them in any nontrivial
# way, for instance read them, it won't work.
class MissingFile(AbstractFile):

  def __init__(self, path, parent):
    super(MissingFile, self).__init__(path, parent)

  def __str__(self):
    return "Missing(%s)" % self.get_path()


# A wrapper around a regular file.
class RegularFile(AbstractFile):

  def __init__(self, path, parent):
    super(RegularFile, self).__init__(path, parent)
    self.lines = None

  def __str__(self):
    return "File(%s)" % self.get_path()

  # Returns an open file handle for the contents of this file.
  def open(self, mode):
    return open(self.get_path(), mode)

  # Returns the contents of this file as a list of strings, one for each line.
  def read_lines(self):
    if self.lines is None:
      self.lines = []
      with self.open("rt") as source:
        for line in source:
          self.lines.append(line)
    return self.lines


# A wrapper around a folder.
class Folder(AbstractFile):

  def __init__(self, path, parent):
    super(Folder, self).__init__(path, parent)

  def __str__(self):
    return "Folder(%s)" % self.get_path()


# A function marked to be exported into build scripts.
class ExportedFunction(object):

  def __init__(self, delegate):
    self.delegate = delegate

  # This gets called by python to produce a bound version of this function.
  def __get__(self, holder, type):
    # We just let the delegate bind itself since we don't need to be able to
    # recognize the bound method, only the function that produces it.
    return self.delegate.__get__(holder, type)


# Annotation used to identify which of ConfigContext's methods are exposed to
# build scripts as toplevel functions.
def export_to_build_scripts(fun):
  return ExportedFunction(fun)


# A context that handles loading an individual mkmk file. Toplevel functions in
# the mkmk becomes method calls on this object. The context is responsible for
# providing convenient utilities for the build scripts, either directly as
# toplevel functions or indirectly through the tool sets (like "c" and "toc")
# and for holding context information for a given mkmk file.
class ConfigContext(object):

  def __init__(self, nodespace, home, full_name):
    self.nodespace = nodespace
    self.env = nodespace.get_environment()
    self.home = home
    self.full_name = full_name

  # Builds the environment dictionary containing all the toplevel functions in
  # the mkmk.
  def get_script_environment(self):
    # Create a copy of the tools environment provided by the shared env.
    result = dict(self.env.get_tools(self))
    for (name, value) in dict(self.__class__.__dict__).items():
      if isinstance(value, ExportedFunction):
        result[name] = getattr(self, name)
    return result

  # Includes the given mkmk into the set of dependencies for this build process.
  @export_to_build_scripts
  def include(self, *rel_mkmk_path):
    full_mkmk = self.home.get_child(*rel_mkmk_path)
    rel_parent_path = rel_mkmk_path[:-1]
    full_name = self.full_name.append(*rel_parent_path)
    mkmk_home = full_mkmk.get_parent()
    subcontext = ConfigContext(self.nodespace, mkmk_home, full_name)
    subcontext.load(full_mkmk)

  @export_to_build_scripts
  def include_dep(self, *rel_mkmk_path):
    rel_parent_path = rel_mkmk_path[:-1]
    dep_name = rel_parent_path[0]
    existing = self.env.get_dep(dep_name)
    if not existing is None:
      # This dep has already been loaded
      return
    full_mkmk = self.home.get_child('deps', *rel_mkmk_path)
    full_name = self.full_name.append('deps', *rel_parent_path)
    mkmk_home = full_mkmk.get_parent()
    bindir = self.nodespace.bindir.get_child('deps', dep_name)
    nodespace = self.env.create_dep(dep_name, mkmk_home, bindir)
    subcontext = ConfigContext(nodespace, mkmk_home, Name.of())
    subcontext.load(full_mkmk)

  # Returns a group node with the given name, creating it if it doesn't already
  # exist.
  @export_to_build_scripts
  def get_group(self, name):
    return self.get_or_create_node(name, node.GroupNode)

  # Returns a node representing a dependency defined outside this context. Note
  # that the external node must already exist, if it doesn't the import order
  # should be changed to make sure nodes are created in the order they're
  # needed. This means that you can't make circular dependencies which is a
  # problem we can solve if it ever becomes necessary.
  @export_to_build_scripts
  def get_external(self, *names):
    return self.nodespace.get_node(Name.of(*names))

  @export_to_build_scripts
  def get_dep_external(self, name, *names):
    nodespace = self.env.get_dep(name)
    return nodespace.get_node(Name.of(*names))

  # Returns a file object representing the root of the source tree, that is,
  # the folder that contains the root .mkmk file.
  @export_to_build_scripts
  def get_root(self):
    return self.nodespace.get_root()

  # Returns a file object representing the dependency with the given name.
  @export_to_build_scripts
  def get_dep(self, name):
    return self.env.get_dep(name).root

  # Returns a file object representing the root of the build output directory.
  @export_to_build_scripts
  def get_bindir(self):
    return self.nodespace.get_bindir()

  # Returns the file object representing the file with the given path under the
  # current folder.
  @export_to_build_scripts
  def get_file(self, *file_path):
    return self.home.get_child(*file_path)

  # Returns a node representing a source file with the given name.
  @export_to_build_scripts
  def get_source_file(self, file_path):
    file = self.home.get_child(file_path)
    return self.get_or_create_node(file_path, node.FileNode, file)

  # Returns a node representing the output of running a custom command.
  @export_to_build_scripts
  def get_custom_exec_file(self, file_path):
    return self.get_or_create_node(file_path, node.CustomExecNode, file_path)

  @export_to_build_scripts
  def get_copy(self, file_path, source_file):
    target_file = self.get_outdir_file(file_path)
    return self.get_or_create_node(file_path, node.CopyNode, source_file, target_file)

  # Returns a node representing the output of running a system command.
  @export_to_build_scripts
  def get_system_exec_file(self, file_path):
    return self.get_or_create_node(file_path, node.SystemExecNode, file_path)

  @export_to_build_scripts
  def get_system_file(self, name):
    return AbstractFile.at(name)

  # Creates a source file that represents the given source file.
  @export_to_build_scripts
  def wrap_source_file(self, file):
    return node.FileNode(None, self, file)

  # Adds a toplevel make alias for the given node.
  @export_to_build_scripts
  def add_alias(self, name, *nodes):
    # Aliases have two names, one fully qualified and one just the basic name.
    alias = self.get_or_create_node(name, node.AliasNode)
    basic_name = Name.of(name)
    self.nodespace.add_node(basic_name, alias)
    for child in nodes:
      alias.add_member(child)
    return alias

  # If a node with the given name already exists within this context returns it,
  # otherwise creates a new node by invoking the given class object with the
  # given arguments and registers the result under the given name.
  def get_or_create_node(self, name, Class, *args):
    node_name = self.get_full_name().append(name)
    return self.nodespace.get_or_create_node(node_name, Class, self, *args)

  # Does the actual work of loading the mkmk file this context corresponds to.
  def load(self, mkmk_file):
    with open(mkmk_file.get_path()) as handle:
      code = compile(handle.read(), mkmk_file.get_path(), "exec")
      exec(code, self.get_script_environment())

  # Returns the full name of the script represented by this context.
  def get_full_name(self):
    return self.full_name

  # Returns a file in the output directory with the given name and, optionally,
  # extension.
  def get_outdir_file(self, name, ext=None):
    if ext:
      full_out_name = self.get_full_name().append("%s.%s" %  (name, ext))
    else:
      full_out_name = self.get_full_name().append(name)
    return self.nodespace.get_bindir().get_child(*full_out_name.get_parts())

  def __str__(self):
    return "Context(%s)" % self.home


# A space of node names. There can be multiple of these, one for the toplevel
# config and one for each dependency. For each dependency there is a fresh
# nodespace such that they can be built the same regardless of whether they
# stand alone or have been imported. There is only one nodespace per dep name
# though so if multiple dependencies import the same dependency only one will
# actually be imported, the first to be encountered, and the rest will reuse it.
class Nodespace(object):

  def __init__(self, env, prefix, root, bindir):
    self.env = env
    self.nodes = {}
    self.prefix = prefix
    self.root = root
    self.bindir = bindir

  # Returns the toplevel shared environment.
  def get_environment(self):
    return self.env

  # If there is already a node registered under the given name returns it,
  # otherwise creates and registers a new one by calling the given constructor
  # with the given arguments.
  def get_or_create_node(self, full_name, Class, *args):
    if full_name in self.nodes:
      return self.nodes[full_name]
    new_node = Class(full_name.get_last_part(), *args)
    return self.add_node(full_name, new_node)

  def add_node(self, full_name, node):
    self.nodes[full_name] = node
    if self.prefix is None:
      global_name = full_name
    else:
      global_name = full_name.prepend(self.prefix)
    self.env.add_node(global_name, node)
    return node

  # Returns the node with the given full name, which must already exist.
  def get_node(self, full_name):
    return self.nodes[full_name]

  # Returns a handle to the root folder.
  def get_root(self):
    return self.root

  # Returns a handle to the binary output folder.
  def get_bindir(self):
    return self.bindir


# The static environment that is shared and constant between all contexts and
# across the lifetime of the build process. The environment is responsible for
# keeping track of nodes and dependencies, and for providing the context-
# independent functionality used by the contexts. Basically, the contexts expose
# the environment's functionality to the tools and build scripts in a convenient
# way, and the environment exposes the results of running those scripts to the
# output generator.
#
# Note that there are two way of addressing nodes, the environment keeps track
# of one and the nodespaces keep track of the other. The nodespaces keep track
# of the names of nodes as seen by each dependency, and there can be multiple
# nodes with the same name as long as they reside in different nodespaces. The
# environment keeps track of all nodes globally and prefix the names by the
# dependencies they live in, making them unique globally.
class Environment(object):

  def __init__(self, options):
    self.options = options
    self.extension_names = options.extension
    self.extensions = None
    self.custom_flags = None
    self.system = None
    self.all_nodes = {}
    self.deps = {}

  def is_noisy(self):
    return self.options.noisy

  def add_node(self, full_name, node):
    self.all_nodes[full_name] = node

  def get_dep(self, name):
    return self.deps.get(name, None)

  def create_dep(self, name, root, bindir):
    result = Nodespace(self, name, root, bindir)
    self.deps[name] = result
    return result

  # Returns the parsed custom flags.
  def get_custom_flags(self):
    assert not self.custom_flags is None
    return self.custom_flags

  # Returns the map of tools for the given context.
  def get_tools(self, context):
    result = {}
    for (name, controller) in self.get_extensions():
      tools = controller.get_tools(context)
      result[name] = tools
    return result

  def get_system(self):
    if self.system is None:
      from . import system
      self.system = system.get(self.options.system)
    return self.system

  # Returns a list of (name, controller) pairs with an entry for each extension
  # enabled for this build process.
  def get_extensions(self):
    if self.extensions is None:
      result = []
      for (name, module) in self.get_modules():
        controller = module.get_controller(self)
        result.append((name, controller))
      self.extensions = result
    return self.extensions

  # Parse any custom flags understood by the extensions.
  def parse_custom_flags(self, flags):
    # Build the argument parser to use.
    parser = argparse.ArgumentParser()
    for (name, controller) in self.get_extensions():
      controller.add_custom_flags(parser)
    args = flags.split()
    self.custom_flags = parser.parse_args(args)

  # Writes the dependency graph in dot format to the given out stream.
  def write_dot_graph(self, out):
    # Escape a string such that it can be used in a dot file without breaking
    # the format.
    def dot_escape(s):
      return re.sub(r'\W', '_', s)
    # Convert an individual key/value edge annotation to a suitably concise
    # string.
    def annot_to_string(key, value):
      if value is True:
        return dot_escape(key)
      elif value is False:
        return "!%s" % dot_escape(key)
      else:
        return "%s: %s" % (dot_escape(key), dot_escape(value))
    # Convert a set of annotations to a string that can be used as a label.
    def annots_to_string(annots):
      return " ".join([annot_to_string(k, v) for (k, v) in annots.items()])
    out.write("digraph G {\n")
    out.write("  rankdir=LR;\n")
    for node in self.all_nodes.values():
      full_name = node.get_full_name()
      escaped = dot_escape(str(full_name))
      display_name = node.get_display_name()
      out.write("  %s [label=\"%s\"];\n" % (escaped, display_name))
      for edge in node.get_direct_edges():
        target = edge.get_target()
        target_name = target.get_full_name()
        escaped_target = dot_escape(str(target_name))
        label = ""
        annots = edge.get_annotations()
        if annots:
          label = " [label=\"%s\"]" % annots_to_string(annots)
        out.write("    %s -> %s%s;\n" % (escaped, escaped_target, label))
    out.write("}\n")

  # Writes the nodes loaded into this environment in Makefile syntax to the
  # given out stream.
  def write_makefile(self, out, bindir):
    makefile = Makefile()
    for node in self.all_nodes.values():
      output_target = node.get_output_target()
      if not output_target:
        # If the node has no output target there's nothing to do to generate it.
        continue
      all_edges = node.get_flat_edges()
      direct_input_files = [e.get_target().get_input_file() for e in all_edges]
      extra_input_files = node.get_computed_dependencies()
      input_files = direct_input_files + extra_input_files
      input_paths = [f.get_path() for f in input_files]
      commands = []
      output_file = node.get_output_file()
      # If there's a file to produce make sure the parent folder exists.
      if not output_file is None:
        output_parent = output_file.get_parent().get_path()
        mkdir_command = self.get_system().get_ensure_folder_command(output_parent)
        commands += mkdir_command.get_actions(self)
      process_command = node.get_command_line(self.get_system())
      if not process_command is None:
        commands += process_command.get_actions(self)
      makefile.add_target(output_target, input_paths, commands, node.is_phony())
    clean_command = self.get_system().get_clear_folder_command(bindir.get_path())
    clean_actions = clean_command.get_actions(self)
    makefile.add_target("clean", [], clean_actions, True)
    makefile.write(out)

  # Returns a list of the python modules supported by this environment.
  def get_modules(self):
    return list(self.generate_tool_modules())

  # Lists all the tool modules and the names under which they should be exposed
  # to build scripts.
  def generate_tool_modules(self):
    for extension in self.extension_names:
      # So yeah, there are subtle differences between the different ways of
      # importing programmatically and the plain import statement which means
      # that I can't for the life of me figure out how to do this cleanly. Also
      # my life is just too short.
      if extension == 'c':
        import mkmk.extension.c
        yield (extension, mkmk.extension.c)
      elif extension == 'py':
        import mkmk.extension.py
        yield (extension, mkmk.extension.py)
      elif extension == 'n':
        import mkmk.extension.n
        yield (extension, mkmk.extension.n)
      elif extension == 'test':
        import mkmk.extension.test
        yield (extension, mkmk.extension.test)
      elif extension == 'toc':
        import mkmk.extension.toc
        yield (extension, mkmk.extension.toc)
      else:
        raise AssertionError("Unknown extension %s" % extension)


# Ensures that the parent folder of the given path exists.
def ensure_parent(path):
  parent = os.path.dirname(path)
  if not os.path.exists(parent):
    os.makedirs(parent)


# The main entry-point class for creating a makefile.
class MkMkMakefile(object):

  def __init__(self, options):
    self.options = options

  def run(self):
    root_mkmk = AbstractFile.at(self.options.config)
    root_mkmk_home = root_mkmk.get_parent()
    bindir = AbstractFile.at(self.options.bindir)
    env = Environment(self.options)
    env.parse_custom_flags(self.options.buildflags)
    nodespace = Nodespace(env, None, root_mkmk_home, bindir)
    context = ConfigContext(nodespace, root_mkmk_home, Name.of())
    context.load(root_mkmk)
    makefile = self.options.makefile
    ensure_parent(makefile)
    env.write_makefile(open(makefile, "wt"), bindir)
