#!/usr/bin/python
#- Copyright 2014 GOTO 10.
#- Licensed under the Apache License, Version 2.0 (see LICENSE).

## Main entry-point. Dispatches to other scripts.

from command import Command, shell_escape
import argparse
import logging
import node
import os
import os.path
import platform
import re
import subprocess
import sys


# Current version of the init script. Bump this to force build scripts to
# regenerate.
_VERSION = 2


# Returns the default value to use for the language.
def get_default_shell():
  system = platform.system()
  if system in ["Linux", "Darwin"]:
    return "sh"
  elif system == "Windows":
    return "bat"
  else:
    return None


_DEFAULT_SYSTEMS = {
  "Windows": "windows",
  "Darwin": "mac"
}
def get_default_system():
  return _DEFAULT_SYSTEMS.get(platform.system(), "posix")


# The main entry-point class.
class MkMk(object):

  def __init__(self, args):
    parser = self.build_option_parser()
    if "--" in args:
      index = args.index("--")
      self.extras = args[index+1:]
      args = args[0:index]
    else:
      self.extras = []
    (self.options, self.unknown) = parser.parse_known_args(args)

  # Parse the options shared between all the different handers.
  def build_option_parser(self):
    parser = argparse.ArgumentParser()
    commands = sorted(self.get_handlers().keys())
    parser.add_argument('command', choices=commands)
    parser.add_argument('--config', default=None, help='The root configuration')
    parser.add_argument('--makefile', default=None,
      help='Name of the makefile to generate')
    parser.add_argument('--bindir', default='out',
      help='The location to store generated files in')
    parser.add_argument('--buildflags', default=None,
      help='Flags to pass through to the build process')
    parser.add_argument('--extension', default=[], action='append',
      help='Specify a build extension to enable')
    parser.add_argument('--noisy', default=False, action='store_true',
      help='Echo all commands being executed')
    parser.add_argument('--shell', default=get_default_shell(),
      help='Which shell to generate a build script for')
    parser.add_argument('--script', default=None,
      help='Name of the build script to generate')
    parser.add_argument('--before', default=None,
      help='Version to compare with when running has_changed')
    parser.add_argument('--system', default=get_default_system(),
      help='The system/os we\'re building on')
    return parser

  # Returns a map from handler names to handlers.
  def get_handlers(self):
    result = {}
    for (name, value) in MkMk.__dict__.items():
      match = re.match(r'handle_(.*)', name)
      if match is None:
        continue
      action = match.group(1)
      result[action] = value
    return result


  # Execute the makefile command.
  def handle_makefile(self):
    self.ensure_no_unknown()
    import makefile
    runner = makefile.MkMkMakefile(self.options)
    runner.run()

  def handle_init(self):
    import init
    mkmk = sys.argv[0]
    return init.generate_build_script(_VERSION, mkmk, self.options, self.unknown)

  def handle_run(self):
    script = self.handle_init()
    command = [script] + self.extras
    return subprocess.check_call(command)

  # Checks whether the contents of this script still MD5-hashes to the given
  # value.
  def handle_has_changed(self):
    if self.options.before == str(_VERSION):
      print("Same")
    else:
      print("Changed")

  # Checks that there were no unknown flags, otherwise dies with an error.
  def ensure_no_unknown(self):
    if len(self.unknown) > 0:
      print "Unknown flags: %s." % " ".join(self.unknown)
      sys.exit(1)

  # Dispatches to the appropriate command.
  def run(self):
    handlers = self.get_handlers()
    command = self.options.command
    handler = handlers[command]
    return handler(self)


def main():
  mkmk = MkMk(sys.argv[1:])
  try:
    mkmk.run()
  except KeyboardInterrupt, ki:
    logging.error("Interrupted; exiting.")
    sys.exit(1)
  except subprocess.CalledProcessError, ce:
    logging.error("%s", ce)
    sys.exit(1)

if __name__ == "__main__":
  main()
