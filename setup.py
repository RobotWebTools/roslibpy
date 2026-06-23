#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from __future__ import absolute_import, print_function

import io
import re
import sys
from glob import glob
from os.path import abspath, basename, dirname, join, splitext

from setuptools import find_packages, setup

here = abspath(dirname(__file__))

# If IronPython, we don't require autobahn/twisted
if sys.platform == "cli":
    requirements = []
else:
    requirements = ["autobahn>=17.10", "twisted[tls]>=17.9"]


def read(*names, **kwargs):
    return io.open(join(here, *names), encoding=kwargs.get("encoding", "utf8")).read()


about = {}
exec(read("src", "roslibpy", "__version__.py"), about)

setup(
    name=about["__title__"],
    version=about["__version__"],
    license=about["__license__"],
    description=about["__description__"],
    author=about["__author__"],
    author_email=about["__author_email__"],
    url=about["__url__"],
    long_description="%s\n%s"
    % (
        re.compile("^.. start-badges.*^.. end-badges", re.M | re.S).sub("", read("README.rst")),
        re.sub(":[a-z]+:`~?(.*?)`", r"``\1``", read("CHANGELOG.rst")),
    ),
    packages=find_packages("src"),
    package_dir={"": "src"},
    py_modules=[splitext(basename(path))[0] for path in glob("src/*.py")],
    include_package_data=True,
    zip_safe=False,
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Operating System :: Unix",
        "Operating System :: POSIX",
        "Operating System :: Microsoft :: Windows",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.3",
        "Programming Language :: Python :: 3.4",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: Implementation :: CPython",
        "Programming Language :: Python :: Implementation :: IronPython",
        "Topic :: Scientific/Engineering",
    ],
    keywords=["ros", "ros-bridge", "robotics", "websockets"],
    install_requires=requirements,
    extras_require={},
    entry_points={"console_scripts": ["roslibpy=roslibpy.__main__:main"]},
)
