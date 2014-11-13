#- Copyright 2014 GOTO 10.
#- Licensed under the Apache License, Version 2.0 (see LICENSE).

## The build node and dependency infrastructure.

from abc import ABCMeta, abstractmethod
from command import Command, shell_escape

# An abstract build node. Build nodes are the basic unit of dependencies in the
# build system. They may or may not correspond to a physical file. You don't
# create Nodes directly, instead each type of node is represented by a subclass
# of Node which is what you actually create.
class Node(object):
  __metaclass__ = ABCMeta

  def __init__(self, name, context):
    self.context = context
    self.name = name
    self.edges = []
    self.full_name = self.context.get_full_name().append(self.name)

  # Returns the name of this node, the last part of the full name of this node.
  def get_name(self):
    return self.name

  # Returns the full absolute name of this node.
  def get_full_name(self):
    return self.full_name

  # Returns the display name that best describes this node. This is only used
  # for describing the node in output, it makes no semantic difference.
  def get_display_name(self):
    return self.get_full_name()

  # Adds an edge from this node to another target node. The edge will be
  # annotated with any keyword arguments specified.
  def add_dependency(self, target, **annots):
    self.edges.append(Edge(target, annots))

  # Returns the raw set of edges, including groups, emanating from this node.
  def get_direct_edges(self):
    return self.edges

  # Generates all edges emanating from this node, flattening groups.
  def get_all_flat_edges(self):
    for edge in self.edges:
      target = edge.get_target()
      for sub_edge in target.flatten_through_edge(edge):
        yield sub_edge

  # Generated the edges emanating from this node, flattening groups. Only edges
  # that match the given annotations are returned.
  def get_flat_edges(self, **annots):
    for edge in self.edges:
      target = edge.get_target()
      for transitive in target.get_flat_edges_through(edge, annots):
        yield transitive

  # Given an edge into this node, generates the set of outgoing edges it should
  # be flattened into that also match the given annotations. This is how groups
  # are implemented: an edge into a group is expanded into the edges pointing
  # through the group.
  def get_flat_edges_through(self, edge, annots):
    # The default behavior is to just yield the edge itself since only groups
    # have special behavior that cause edges to be flattened.
    if edge.has_annotations(annots):
      yield edge

  # Returns the string file paths of all the dependencies from this node that
  # have been annotated in the specified way. Edges with additional annotations
  # are included in the result so specifying an empty annotation set will give
  # all the dependencies.
  def get_input_paths(self, **annots):
    return [n.get_input_file().get_path() for n in self.get_input_nodes(**annots)]

  # Returns the nodes of all the dependencies from this node.
  def get_input_nodes(self, **annots):
    edges = self.get_flat_edges(**annots)
    return [e.get_target() for e in edges]

  # Returns the string file path of the file to output for this node. If this
  # node has no associated output file returns None.
  def get_output_path(self):
    output_file = self.get_output_file()
    if output_file is None:
      return None
    else:
      return output_file.get_path()

  # Returns the file that represents this file when used as input to actions.
  def get_input_file(self):
    result = self.get_output_file()
    assert not result is None
    return result

  # Returns the file that represents the output of processing this node. If
  # the node doesn't require processing returns None.
  def get_output_file(self):
    return None

  # Returns the name of the target produced by this node.
  @abstractmethod
  def get_output_target(self):
    pass

  # Returns the context this node was created within.
  def get_context(self):
    return self.context

  # A hook subclasses can use to add extra, otherwise untracked, files that a
  # node depends on.
  def get_computed_dependencies(self):
    return []

  # Should the corresponding makefile target be marked as phony?
  def is_phony(self):
    return False

  def __str__(self):
    return "%s(%s, %s)" % (type(self).__name__, self.context, self.name)


# A node that has no corresponding physical file.
class VirtualNode(Node):
  __metaclass__ = ABCMeta

  def get_output_target(self):
    return self.get_name()

  def get_command_line(self, system):
    return None

  def is_phony(self):
    return True


# A node associated with a physical file.
class PhysicalNode(Node):

  def get_output_target(self):
    output_file = self.get_output_file()
    if output_file:
      return output_file.get_path()
    else:
      return None


# A "dumb" node representing a file. If you need any kind of file type specific
# behavior use a subclass of PhysicalNode instead.
class FileNode(PhysicalNode):

  def __init__(self, name, context, handle):
    super(FileNode, self).__init__(name, context)
    self.handle = handle

  def get_input_file(self):
    return self.handle

  def get_run_command_line(self, platform):
    return self.handle.get_path()


# A node representing the execution of a custom command.
class CustomExecNode(PhysicalNode):

  def __init__(self, name, context, subject):
    super(CustomExecNode, self).__init__(name, context)
    self.subject = subject
    self.args = []
    self.env = []
    self.title = None

  def get_output_file(self):
    return self.get_context().get_outdir_file(self.subject)

  def get_command_line(self, system):
    runner = self.get_runner_command(system)
    outpath = self.get_output_path()
    args = " ".join(self.get_arguments())
    raw_command_line = "%s %s" % (runner, args)
    if len(self.env) > 0:
      raw_command_line = system.run_with_environment(raw_command_line, self.env)
    if self.should_tee_output():
      result = system.get_safe_tee_command(raw_command_line, outpath)
    else:
      result = Command(raw_command_line)
    if self.title is None:
      title = "Running %s" % self.get_full_name()
    else:
      title = self.title
    result.set_comment(title)
    return result

  # Returns the executable to run.
  def get_runner_command(self, platform):
    [runner_node] = self.get_input_nodes(runner=True)
    return runner_node.get_run_command_line(platform)

  # Should the contents of the output file be printed on successful completion?
  def should_tee_output(self):
    return False

  # Sets the executable used to run this node case.
  def set_runner(self, node):
    self.add_dependency(node, runner=True)
    return self

  # Sets the title of the node, the message to print when running it.
  def set_title(self, title):
    self.title = title
    return self

  # Sets the (string) arguments to pass to the runner.
  def set_arguments(self, *args):
    self.args = args
    return self

  def add_env(self, key, value):
    self.env.append((key, value, "replace"))
    return self

  # Returns the argument list to pass when executing this node.
  def get_arguments(self):
    return self.args


# A custom executable node that calls a system command.
class SystemExecNode(CustomExecNode):

  def __init__(self, name, context, subject):
    super(SystemExecNode, self).__init__(name, context, subject)
    self.command = None

  def set_command(self, command):
    self.command = command
    return self

  def get_runner_command(self, platform):
    return self.command


# Copies the source file to the target.
class CopyNode(PhysicalNode):

  def __init__(self, name, context, source, target):
    super(CopyNode, self).__init__(self, context)
    self.add_dependency(source, source=True)
    self.target = target

  def get_output_file(self):
    return self.target

  def get_command_line(self, system):
    [source_node] = self.get_input_nodes(source=True)
    inpath = source_node.get_output_file().get_path()
    outpath = self.target.get_path()
    return system.get_copy_command(inpath, outpath)


# A dependency between nodes. An edge is like a pointer from one node to another
# but additionally carries a set of annotations that control what the pointer
# means. For instance, an object file may depend on both a source file and its
# headers but the compilation command the produces the object only requires the
# source file to be passed, not the headers. In that case the dependencies would
# be annotated differently to account for this difference in how they should be
# handled.
#
# Unlike Node there is only one Edge type which can be used directly.
class Edge(object):

  def __init__(self, target, annots):
    self.target = target
    self.annots = annots

  # Returns the target node for this edge.
  def get_target(self):
    return self.target

  # Returns this node's annotations as a dict.
  def get_annotations(self):
    return self.annots

  # Returns true if this edge is annotated as specified by the given query. Any
  # annotation mentioned in the query must have the same value as in the query,
  # any additional annotations not mentioned are ignored.
  def has_annotations(self, query):
    for (key, value) in query.items():
      if not (self.annots.get(key, None) == value):
        return False
    return True


# A node that works as a stand-in for a set of other nodes. If you know you're
# going to be using the same set of nodes in a bunch of places creating a single
# group node to represent them is a convenient way to handle that.
class GroupNode(VirtualNode):

  # Adds a member to this group.
  def add_member(self, node):
    self.add_dependency(node)

  # A group node doesn't produce any actual output, it is resolved directly into
  # anything that depends on it.
  def get_output_target(self):
    return None

  def get_flat_edges_through(self, edge, annots):
    # If the edge we used to get here has the annotations then we consider them
    # to be satisfied and remove any restrictions on the following nodes.
    if edge.has_annotations(annots):
      annots = {}
    for target in self.get_flat_edges(**annots):
      yield target


# A different name for a group of nodes. Similar to a group except that a target
# is produces so the alias can be built independently of any physical targets.
class AliasNode(GroupNode):

  # Unlike a normal group an alias causes a target to be generated.
  def get_output_target(self):
    prefix = self.context.nodespace.get_prefix()
    if prefix is None:
      return self.get_name()
    else:
      return "%s_%s" % (prefix, self.get_name())
