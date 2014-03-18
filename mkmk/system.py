# Copyright 2013 the Neutrino authors (see AUTHORS).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


# Code that controls how the build works on different platforms.


from command import Command, shell_escape
from abc import ABCMeta, abstractmethod
import os.path


# A system is a set of tools used to interact with the current platform etc.
class System(object):
  __metaclass__ = ABCMeta

  # Returns the command for ensuring that the folder with the given name
  # exists.
  @abstractmethod
  def get_ensure_folder_command(self, folder):
    pass

  # Returns the command that runs the given command line, printing the output
  # and also storing it in the given outpath, but deletes the outpath again and
  # fails if the command line fails. Sort of how you wish tee could work.
  @abstractmethod
  def get_safe_tee_command(self, command_line, outpath):
    pass

  # Returns a command the executes the given command in an environment augmented
  # with the given bindings.
  @abstractmethod
  def run_with_environment(self, command, env):
    pass

  # Returns a command that recursively removes the given folder without failing
  # if the folder doesn't exist.
  @abstractmethod
  def get_clear_folder_command(self, folder):
    pass


class PosixSystem(System):

  def get_ensure_folder_command(self, folder):
    command = "mkdir -p %s" % shell_escape(folder)
    return Command(command)

  def get_clear_folder_command(self, folder):
    command = "rm -rf %s" % (shell_escape(folder))
    comment = "Clearing '%s'" % folder
    return Command(command).set_comment(comment)

  def get_safe_tee_command(self, command_line, outpath):
    params = {
      "command_line": command_line,
      "outpath": outpath
    }
    parts = [
      "%(command_line)s > %(outpath)s || echo > %(outpath)s.fail",
      "cat %(outpath)s",
      "if [ -f %(outpath)s.fail ]; then rm %(outpath)s %(outpath)s.fail; false; else true; fi",
    ]
    comment = "Running %(command_line)s" % params
    return Command(*[part % params for part in parts])

  def run_with_environment(self, command, env):
    envs = []
    for (name, value, mode) in env:
      if mode == "append":
        envs.append("%(name)s=$%(name)s:%(value)s" % {
          "name": name,
          "value": value
        })
      else:
        raise Exception("Unknown mode %s" % mode)
    return "%s %s" % (" ".join(envs), command)



class WindowsSystem(System):

  def get_ensure_folder_command(self, folder):
    # Windows mkdir doesn't have an equivalent to -p but we can use a bit of
    # logic instead.
    path = shell_escape(folder)
    action = "if not exist %(path)s mkdir %(path)s" % {"path": path}
    return Command(action)

  def get_clear_folder_command(self, folder):
    path = shell_escape(folder)
    comment = "Clearing '%s'" % path
    action = "if exist %(path)s rmdir /s /q %(path)s" % {"path": path}
    return Command(action).set_comment(comment)

  def get_safe_tee_command(self, command_line, outpath):
    params = {
      "command_line": command_line,
      "outpath": outpath
    }
    parts = [
      "%(command_line)s > %(outpath)s || echo > %(outpath)s.fail",
      "type %(outpath)s",
      "if exist %(outpath)s.fail (del %(outpath)s %(outpath)s.fail && exit 1) else (exit 0)",
    ]
    comment = "Running %(command_line)s" % params
    return Command(*[part % params for part in parts])

  def run_with_environment(self, command, env):
    envs = []
    for (name, value, mode) in env:
      if mode == "append":
        envs.append("set %(name)s=%%%(name)s%%:%(value)s" % {
          "name": name,
          "value": value
        })
      else:
        raise Exception("Unknown mode %s" % mode)
    return "%s && %s" % (" && ".join(envs), command)


def get(os):
  if os == 'posix':
    return PosixSystem()
  elif os == 'windows':
    return WindowsSystem()
  else:
    raise AssertionError("Unknown system '%s'." % os)
