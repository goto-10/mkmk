#!/usr/bin/python
# Copyright 2013 the Neutrino authors (see AUTHORS).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


# Tools for generating test table-of-contents.


import re
import sys


def main(args):
  headers = []
  for arg in args:
    for line in open(arg):
      match = re.match(r"TEST\((.*)\)", line)
      if match:
        headers.append(match.group(1))
  for header in headers:
    print("DECLARE_TEST(%s);" % header)
  print("ENUMERATE_TESTS_HEADER {")
  for header in headers:
    print("  ENUMERATE_TEST(%s);" % header)
  print("}")


# Python has, wonderfully, changed how imports work between versions 2 and 3 and
# I haven't found a way to do the import below in a way that works both in 2 and
# 3 _and_ both as a module and a stand-alone executable. So to make the stand-
# alone executable work in python 2 this part comes first and exits before that
# import is reached.
if __name__ == '__main__':
  main(sys.argv[1:])
  sys.exit(0)


from ..command import Command, shell_escape
from .. import extend
from .. import node


# Node representing the TOC file.
class TocNode(node.PhysicalNode):

  def __init__(self, name, context):
    super(TocNode, self).__init__(name, context)
    self.generator = None

  def get_output_file(self):
    return self.get_context().get_outdir_file(self.get_name())

  def get_command_line(self, platform):
    outfile = self.get_output_path()
    infiles = self.get_input_paths(test=True)
    command = "%(generator)s %(infiles)s > %(outfile)s" % {
      "generator": self.generator.get_path(),
      "infiles": " ".join(infiles),
      "outfile": outfile
    }
    return Command(command)

  # Add a test case to include in the TOC.
  def add_test(self, node):
    self.add_dependency(node, test=True)

  # Sets the file that generates the TOC from the test files.
  def set_generator(self, generator):
    self.generator = generator


# The TOC tools, exposed as "toc" to build scripts.
class TocTools(extend.ToolSet):

  # Returns a node representing a TOC file with the given name.
  def get_toc_file(self, name):
    return self.get_context().get_or_create_node(name, TocNode)


class TocController(extend.ToolController):

  def get_tools(self, context):
    return TocTools(context)


# Entry-point used by the framework to get the tool set for the given context.
def get_controller(env):
  return TocController(env)
