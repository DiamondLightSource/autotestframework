from setuptools import setup
        
# these lines allow the version to be specified in Makefile.private
import os
version = os.environ.get("MODULEVER", "0.0")
        
setup(
#    install_requires = ['cothread'], # require statements go here
    name = 'dls_autotestframework',
    version = version,
    description = 'Module',
    author = 'fgz73762',
    author_email = 'fgz73762@rl.ac.uk',    
    packages = ['dls_autotestframework'],
    entry_points = {'console_scripts': [
        'dls-run-tests = dls_autotestframework.autotestframework:main',
        'dls-create-coverage-report.py = dls_autotestframework.createcoveragereport:main'
        ]},
#    include_package_data = True, # use this to include non python files
    zip_safe = False
    )        
