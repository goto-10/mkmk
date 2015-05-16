# Copyright 2013 the Neutrino authors (see AUTHORS).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


# Code that controls how the build works on different platforms.


from abc import ABCMeta, abstractmethod
from command import Command, shell_escape
import os.path
import re


# A system is a set of tools used to interact with the current platform etc.
class System(object):
  __metaclass__ = ABCMeta

  def __init__(self, os):
    self.os = os

  def get_os(self):
    return self.os

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
  def run_with_environment(self, command, env, args=[]):
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

  def run_with_environment(self, command, env, args=[]):
    envs = []
    for (name, value, mode) in env:
      if type(value) == list:
        value = ":".join(value)
      if mode == "append":
        envs.append("%(name)s=$$%(name)s:%(value)s" % {
          "name": name,
          "value": value
        })
      elif mode == "replace":
        envs.append("%(name)s=%(value)s" % {
          "name": name,
          "value": value
        })
      else:
        raise Exception("Unknown mode %s" % mode)
    return "%s %s %s" % (" ".join(envs), command, " ".join(args))

  def get_copy_command(self, source, target):
    command = "cp %s %s" % (shell_escape(source), shell_escape(target))
    comment = "Copying to '%s'" % target
    return Command(command).set_comment(comment)


def cmd_escape(str):
  return str.replace("\"", "\\\"")

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
      "command_line": command_line.replace("\\", "\\\\"),
      "outpath": outpath
    }
    parts = [
      "%(command_line)s > %(outpath)s || echo > %(outpath)s.fail",
      "type %(outpath)s",
      "if exist %(outpath)s.fail (del %(outpath)s %(outpath)s.fail && exit 1) else (exit 0)",
    ]
    comment = "Running %(command_line)s" % params
    return Command(*[part % params for part in parts])

  def run_with_environment(self, command, env, args=[]):
    envs = []
    for (name, value, mode) in env:
      if type(value) == list:
        value = ";".join(value)
      if mode == "append":
        envs.append("set \"%(name)s=%%%(name)s%%\;%(value)s\"" % {
          "name": name,
          "value": value
        })
      elif mode == "replace":
        envs.append("set \"%(name)s=%(value)s\"" % {
          "name": name,
          "value": value
        })
      else:
        raise Exception("Unknown mode %s" % mode)
    subcommand = "%s %s" % (command, " ".join(args))
    return "cmd /c \"%s && %s\"" % (" && ".join(envs), cmd_escape(subcommand))

  def get_copy_command(self, source, target):
    command = "copy %s %s" % (shell_escape(source), shell_escape(target))
    comment = "Copying to '%s'" % target
    return Command(command).set_comment(comment)


def get(os):
  if (os == 'posix') or (os == 'mac'):
    return PosixSystem(os)
  elif os == 'windows':
    return WindowsSystem(os)
  else:
    raise AssertionError("Unknown system '%s'." % os)
