#- Copyright 2013 GOTO 10.
#- Licensed under the Apache License, Version 2.0 (see LICENSE).

import setuptools

setuptools.setup(
  name = "Mkmk",
  version = "0.0.1",
  description = "Build system",
  author = "GOTO 10",
  url = "https://github.com/goto-10/mkmk",
  packages = setuptools.find_packages(),
  entry_points = {
    'console_scripts': [
      'mkmk = mkmk.main:main',
    ]
  },
)
