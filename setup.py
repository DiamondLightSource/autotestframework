# setup.py file for building autotestframework
from setuptools import setup, find_packages, Extension

# this line allows the version to be specified in the release script
try:
	version = version
except:
	version = "0.0"

setup(
	# install_requires allows you to import a specific version of a module in your scripts 
#	install_requires = ['dls.ca2==1.6'],
	# setup_requires lets us use the site specific settings for installing scripts
	setup_requires = ["dls.environment==1.0"],
	# name of the module
	name = "dls.autotestframework",
	# version: over-ridden by the release script
	version = version,
	packages = ["dls","dls.autotestframework"],
	package_dir = {	'dls': 'dls',
					'dls.autotestframework': 'src'},
	# define console_scripts to be 
	entry_points = {'console_scripts': ['dls-run-tests = dls.autotestframework.autotestframework:main']},
	include_package_data = True,
	zip_safe = False
	)
