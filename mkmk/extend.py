#- Copyright 2014 GOTO 10.
#- Licensed under the Apache License, Version 2.0 (see LICENSE).

## Utilities used for creating build extensions.

from abc import ABCMeta, abstractmethod

# Abstract superclass of the tool sets loaded implicitly into each context.
# There can be many of these, one for each context.
class ToolSet(object):
  __metaclass__ = ABCMeta

  def __init__(self, context):
    self.context = context

  # Returns the context this tool set belongs to.
  def get_context(self):
    return self.context


# Controller for this kind of extension. There is only one of these for each
# kind of extension.
class ToolController(object):
  __metaclass__ = ABCMeta

  def __init__(self, env):
    self.env = env

  # Returns the build environment.
  def get_environment(self):
    return self.env

  # Gives this controller an opportunity to add some extra custom flags. By
  # default does nothing.
  def add_custom_flags(self, parser):
    pass

  # Returns a toolset instance, given a concrete context.
  @abstractmethod
  def get_tools(self, context):
    pass
