const { python, ProjectType, Project } = require('projen');
const version = '0.1.0';

const project = new Project({});
project.gitignore.addPatterns('.python-version', '.idea');

const DEFAULT_POETRY_OPTIONS = {
  authors: [
    'Hal Blackburn <hwtb2@cam.ac.uk>'
  ],
  packages: [{include: 'tilediiif'}],
}
const DEFAULT_OPTIONS = {
  parent: project,
  sample: false,
  version: version,
  pip: false,
  setuptools: false,
  poetry: true,
  projectType: ProjectType.APP,
  pytest: true,
  venv: false,

  poetryOptions: {
    ...DEFAULT_POETRY_OPTIONS,
  },
}


const tilediiifCore = new python.PythonProject({
  ...DEFAULT_OPTIONS,
  outdir: 'tilediiif.core',
  name: 'tilediiif.core',

  deps: [
    "docopt@^0.6.2",
    "jsonpath-rw@^1.4",
    "jsonschema@^3.0",
    "toml@^0.10.0",
  ],
  devDeps: [
    "pytest@^6.2.4",
    "hypothesis@^4.36",
  ],
});
const tilediiifCorePyprojectToml = tilediiifCore.tryFindObjectFile('pyproject.toml');
tilediiifCorePyprojectToml.addOverride('tool.poetry.packages', [{include: 'tilediiif'}]);


const tilediiifTools = new python.PythonProject({
  ...DEFAULT_OPTIONS,
  outdir: 'tilediiif.tools',
  name: 'tilediiif.tools',

  poetryOptions: {
    ...DEFAULT_POETRY_OPTIONS,
    scripts: {
      infojson: 'tilediiif.tools.infojson:main',
      'iiif-tiles': 'tilediiif.tools.tilelayout:main',
      'dzi-tiles': 'tilediiif.tools.dzi_generation_faulthandler:run_dzi_generation_with_faulthandler_enabled',
    },
  },

  deps: [
    "tilediiif.core",  // overriden below to point to local path
    "python@^3.7",
    "docopt@^0.6.2",
    "rfc3986@^1.3",
    "pyvips@^2.1",
  ],
  devDeps: [
    "pytest@^6.2.4",
    "hypothesis@^4.36",
    "toml@^0.10.0",
    "tox@^3.14",
    "flake8@^3.7",
    "yappi@^1.0",
    "pytest-subtesthack@0.1.1",
    "ipython@^7.8",
    "httpie@^1.0",
    "black@^21.5b1",
    "flake8-bugbear@^19.8",
    "isort@^4.3",
    "pytest-lazy-fixture@^0.6.1",
    "numpy@^1.17",
  ],
});
const tilediiifToolsPyprojectToml = tilediiifTools.tryFindObjectFile('pyproject.toml');
tilediiifToolsPyprojectToml.addOverride('tool.poetry.dependencies.tilediiif\\.core', {path: '../tilediiif.core', develop: true});


const tilediiifServer = new python.PythonProject({
  ...DEFAULT_OPTIONS,
  outdir: 'tilediiif.server',
  name: 'tilediiif.server',

  deps: [
    "python@^3.7",
    "falcon@^2.0",
    "tilediiif.core",
  ],
  devDeps: [
    "pytest@^6.2.4",
  ],
});
const tilediiifServerPyprojectToml = tilediiifServer.tryFindObjectFile('pyproject.toml');
tilediiifServerPyprojectToml.addOverride('tool.poetry.dependencies.tilediiif\\.core', {path: '../tilediiif.core',  develop: true});


project.synth();
