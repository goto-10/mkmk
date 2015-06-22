# Copyright 2013 the Neutrino authors (see AUTHORS).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


# Code that controls how the build works on different platforms.


from abc import ABCMeta, abstractmethod
from command import Command, shell_escape
import os.path
import re
import subprocess
import sys


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

  # Returns the a new command builder that can be used to build commands on this
  # platform.
  @abstractmethod
  def new_command_builder(self, executable, *args):
    pass

  # Returns a command that recursively removes the given folder without failing
  # if the folder doesn't exist.
  @abstractmethod
  def get_clear_folder_command(self, folder):
    pass


class CommandBuilder(object):

  def __init__(self, executable, *args):
    self.executable = executable
    self.args = args
    self.comment = None
    self.tee_dest = None
    self.env = []

  def set_comment(self, comment):
    self.comment = comment
    return self

  def set_tee_destination(self, dest):
    self.tee_dest = dest
    return self

  def add_env(self, env):
    self.env = list(self.env) + list(env)
    return self

  def add_arguments(self, args):
    self.args = list(self.args) + list(args)
    return self


class PosixCommandBuilder(CommandBuilder):

  def build(self):
    args = map(shell_escape, self.args)
    raw_command = "%s %s" % (self.executable, " ".join(args))
    if len(self.env) > 0:
      envs = []
      for (name, value, mode) in self.env:
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
      raw_command = "%s %s" % (" ".join(envs), raw_command)
    if self.tee_dest:
      params = {
        "command_line": raw_command,
        "outpath": self.tee_dest
      }
      parts = [
        "%(command_line)s > %(outpath)s 2>&1 || echo > %(outpath)s.fail",
        "cat %(outpath)s",
        "if [ -f %(outpath)s.fail ]; then rm %(outpath)s %(outpath)s.fail; false; else true; fi",
      ]
      result = Command(*[part % params for part in parts])
    else:
      result = Command(raw_command)
    if self.comment:
      result.set_comment(self.comment)
    return result


class PosixSystem(System):

  def new_command_builder(self, executable, *args):
    return PosixCommandBuilder(executable, *args)

  def get_ensure_folder_command(self, folder):
    return (self
        .new_command_builder("mkdir", "-p", folder)
        .build())

  def get_clear_folder_command(self, folder):
    return (self
        .new_command_builder("rm", "-rf", folder)
        .set_comment("Clearing '%s'" % folder)
        .build())

  def get_copy_command(self, source, target):
    return (self
      .new_command_builder("cp", source, target)
      .set_comment("Copying to '%s'" % target)
      .build())

  def auto_resolve_library(self, name):
    process = subprocess.Popen(["pkg-config", "--cflags", "--libs", name], stdout=subprocess.PIPE)
    (stdout, stderr) = process.communicate()
    if process.returncode != 0:
      sys.exit(1)
    flags = stdout.split()
    includes = [f[2:] for f in flags if f.startswith("-I")]
    libs = [f[2:] for f in flags if f.startswith("-l")]
    return (includes, libs)

def cmd_escape(str):
  return re.sub(r'([\"])', r"\\\g<1>", str)


class WindowsCommandBuilder(CommandBuilder):

  def build(self):
    args = map(shell_escape, self.args)
    raw_command = "%s %s" % (self.executable, " ".join(args))
    if len(self.env) > 0:
      envs = []
      for (name, value, mode) in self.env:
        if type(value) == list:
          value = ";".join(value)
        if mode == "append":
          env = "set \"%(name)s=%%%(name)s%%;%(value)s\"" % {
            "name": name,
            "value": value
          }
        elif mode == "replace":
          env = "set \"%(name)s=%(value)s\"" % {
            "name": name,
            "value": value
          }
        else:
          raise Exception("Unknown mode %s" % mode)
        envs.append(env)
      raw_command = "cmd /C \"%s && %s\"" % (" && ".join(envs), cmd_escape(raw_command))
    if self.tee_dest:
      params = {
        "command_line": raw_command,
        "outpath": self.tee_dest
      }
      parts = [
        "%(command_line)s > %(outpath)s 2>&1 || echo > %(outpath)s.fail",
        "type %(outpath)s",
        "if exist %(outpath)s.fail (del %(outpath)s %(outpath)s.fail && exit 1) else (exit 0)",
      ]
      result = Command(*[part % params for part in parts])
    else:
      result = Command(raw_command)
    if self.comment:
      result.set_comment(self.comment)
    return result


class WindowsSystem(System):

  def new_command_builder(self, executable, *args):
    return WindowsCommandBuilder(executable, *args)

  def get_ensure_folder_command(self, folder):
    # Windows mkdir doesn't have an equivalent to -p but we can use a bit of
    # logic instead.
    return (self
        .new_command_builder("if", "not", "exist", folder, "mkdir", folder)
        .build())

  def get_clear_folder_command(self, folder):
    return (self
        .new_command_builder("if", "exist", folder, "rmdir", "/s", "/q", folder)
        .set_comment("Clearing '%s'" % folder)
        .build())

  def get_copy_command(self, source, target):
    return (self
        .new_command_builder("copy", source, target)
        .set_comment("Copying to '%s'" % target)
        .build())


def get(os):
  if (os == 'posix') or (os == 'mac'):
    return PosixSystem(os)
  elif os == 'windows':
    return WindowsSystem(os)
  else:
    raise AssertionError("Unknown system '%s'." % os)
