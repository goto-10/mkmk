#- Copyright 2013 GOTO 10.
#- Licensed under the Apache License, Version 2.0 (see LICENSE).

## Functionality related to building shell commands.

import re

# A command to be executed on the command-line along with a comment. In non-
# verbose mode only the comment will be displayed while building.
class Command(object):

  def __init__(self, *parts):
    self.parts = parts
    self.comment = None

  def set_comment(self, comment):
    self.comment = comment
    return self

  @staticmethod
  def empty():
    return Command()

  def get_actions(self, env):
    parts = list(self.parts)
    if not env.is_noisy():
      parts = ["@%s" % a for a in parts]
    if self.comment:
      parts = ["@echo '%s'" % self.comment] + parts
    return parts

# Escapes a string such that it can be passed as an argument in a shell command.
def shell_escape(s):
  return re.sub(r'([\s()\\])', r"\\\g<1>", s)
