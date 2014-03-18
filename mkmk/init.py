#!/usr/bin/python
# Copyright 2013 the Neutrino authors (see AUTHORS).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


import os
import os.path
import platform
import sys


try:
  import plankton
except ImportError, e:
  print "Couldn't import plankton. Before init'ing you have to run"
  print ""
  print "  sudo ./tools/install-deps.sh"
  sys.exit(1)


# Returns the default value to use for the language.
def get_default_shell():
  system = platform.system()
  if system == "Linux":
    return "sh"
  elif system == "Windows":
    return "bat"
  else:
    return None


_SH_TEMPLATE = """\
#!/bin/sh
# This file was generated by the init tool invoked as
#
#     %(init_tool)s %(init_args)s
#
# You generally don't want to edit it by hand. Instead, either change the init 
# tool or copy it to another name and then edit that to avoid your changes being
# randomly overwritten.

# Bail out on the first error.
set -e

# The version of the init script the produced this build script.
INIT_VERSION="%(version)s"

# Check whether init.py has changed. If it has regenerate this file and run it
# again.
INIT_CHANGED=$(%(init_tool)s has_changed --before $INIT_VERSION)
if [ $INIT_CHANGED = "Changed" ]; then
  echo \# The workspace initializer has changed. Reinitializing by running
  echo \#
  echo \#   %(init_tool)s %(init_args)s
  echo \#
  %(init_tool)s %(init_args)s
  echo \# Build script regenerated. Running the new script like so:
  echo \#
  echo \#   "$0" "$*"
  echo \#
  "$0" "$*"
  exit $?
fi

# Rebuild makefile every time.
%(mkmk_tool)s makefile \\
  --config "%(config)s" \\
  --bindir "%(bindir)s" \\
  --makefile "%(Makefile.mkmk)s" \\
  --extension c \\
  --extension n \\
  --extension py \\
  --extension test \\
  --extension toc \\
  --buildflags="%(variant_flags)s" \\
  %(cond_flags)s

# Delegate to the resulting makefile.
make -f "%(Makefile.mkmk)s" $*
"""


_BAT_TEMPLATE = """\
@echo off

REM This file was generated by the init tool invoked as
REM
REM     %(init_tool)s %(init_args)s
REM
REM You generally don't want to edit it by hand. Instead, either change the init 
REM tool or copy it to another name and then edit that to avoid your changes
REM being randomly overwritten.

for /f "tokens=*" %%%%a in (
  'python %(init_tool)s has_changed --before "%(init_version)s"'
) do (
  set init_changed=%%%%a
)

if "%%init_changed%%" == "Changed" (
  echo # The workspace initializer has changed. Reinitializing by running
  echo #
  echo #   python %(init_tool)s %(init_args)s
  python %(init_tool)s %(init_args)s
  if %%errorlevel%% neq 0 exit /b %%errorlevel%%
  echo #
  echo # Build script regenerated. Running the new script like so:
  echo #
  echo #   %%0 %%*
  call %%0 %%*
) else (
  python %(mkmk_tool)s makefile --config "%(config)s" --bindir "%(bindir)s" --makefile "%(Makefile.mkmk)s" --toolchain msvc %(variant_flags)s
  if %%errorlevel%% neq 0 exit /b %%errorlevel%%

  nmake /nologo -f "%(Makefile.mkmk)s" %%*
  if %%errorlevel%% neq 0 exit /b %%errorlevel%%
)
"""


# Map from shell names to the data used to generate their build scripts.
_SHELLS = {
  "sh": (_SH_TEMPLATE, "%s.sh"),
  "bat": (_BAT_TEMPLATE, "%s.bat")
}


# Checks that the flags are sane, otherwise bails.
def validate_flags(flags):
  if flags.shell is None:
    raise Exception("Couldn't determine which shell to use; use --shell.")
  if not flags.shell in _SHELLS:
    options = sorted(_SHELLS.keys())
    raise Exception("Unknown shell %s; possible values are %s." % (flags.shell, options))


# Returns the neutrino root folder path.
def get_neutrino_root(flags):
  if flags.root:
    # An explicit root is given so we just use that.
    return flags.root
  else:
    # Try to infer the root from the script path.
    import os
    import os.path
    script_path = __file__
    script_neutrino_root = os.path.dirname(os.path.dirname(script_path))
    if not (":" in script_neutrino_root):
      # We've got a path we can use; return it.
      return script_neutrino_root
    else:
      # We have a candidate but it contains a colon which will make 'make'
      # unhappy. This will most likely be from windows (as in "C:\...") so try
      # to remove it by using a relative path instead.
      cwd = os.getcwd()
      prefix = os.path.commonprefix([cwd, script_neutrino_root])
      return script_neutrino_root[len(prefix)+1:]


# Returns the name of the build script to generate.
def get_script_name(flags):
  if flags.script:
    return flags.script
  else:
    # No script is explicitly passed so default to "build" with the correct
    # extension in the current directory.
    workspace_root = os.getcwd()
    shell = _SHELLS[flags.shell]
    return os.path.join(workspace_root, shell[1] % "build")


# Returns the name of the generated makefile.
def get_makefile_name(flags):
  return os.path.join(flags.bindir, "Makefile.mkmk")


# Generates a build script of the appropriate type.
def generate_build_script(version, mkmk, flags, variant_flags):
  validate_flags(flags)
  config = flags.config
  if not os.path.exists(config):
    raise Exception("Couldn't find the root build script as %s" % config)
  filename = get_script_name(flags)
  shell = _SHELLS[flags.shell]
  template = shell[0]
  cond_flags = []
  if flags.noisy:
    cond_flags.append('--noisy')
  makefile_src = template % {
    "version": version,
    "init_tool": mkmk,
    "init_args": " ".join(sys.argv[1:]),
    "mkmk_tool": "mkmk",
    "config": config,
    "bindir": flags.bindir,
    "Makefile.mkmk": get_makefile_name(flags),
    "variant_flags": " ".join(variant_flags),
    "cond_flags": " ".join(cond_flags)
  }
  with open(filename, "wt") as out:
    out.write(makefile_src)
  # Make the build script executable
  import stat
  st = os.stat(filename)
  os.chmod(filename, st.st_mode | stat.S_IEXEC)
