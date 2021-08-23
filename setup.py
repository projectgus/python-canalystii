#!/usr/bin/env python
import io
import os

from setuptools import find_packages, setup

# Import the README and use it as the long-description.
root_dir = os.path.abspath(os.path.dirname(__file__))
with io.open(os.path.join(root_dir, "README.md"), encoding="utf-8") as f:
    long_description = "\n" + f.read()

setup(
    name="canalystii",
    version="0.1-dev",
    description="Python userspace driver for Canalyst-II CAN analyzer.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Angus Gratton",
    author_email="todo@example.com",
    url="https://github.com/projectgus/python-canalystii",
    packages=find_packages(exclude=["tests"]),
    install_requires=["pyusb>=1.2.0"],
    include_package_data=True,
    license="MIT",
    classifiers=[
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: Implementation :: CPython",
        "Programming Language :: Python :: Implementation :: PyPy",
    ],
)
