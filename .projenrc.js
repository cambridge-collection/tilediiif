const { python, ProjectType, TextFile } = require('projen');
const { PROJEN_MARKER } = require('projen/common');
const { TaskCategory } = require('projen/tasks');

const TILEDIIIF_TOOLS_VERSION = '0.1.0';
const TILEDIIIF_SERVER_VERSION = '0.1.0';
const TILEDIIIF_CORE_VERSION = '0.1.0';

const DEFAULT_POETRY_OPTIONS = {
  authors: [
    'Hal Blackburn <hwtb2@cam.ac.uk>'
  ],
  packages: [{include: 'tilediiif'}],
}
const DEFAULT_OPTIONS = {
  sample: false,
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

const PROJECT_DIR_NAMES = ['tilediiif.tools', 'tilediiif.server', 'tilediiif.core'];
const PROJECT_PATHS = PROJECT_DIR_NAMES.join(' ');


const rootProject = new python.PythonProject({
  ...DEFAULT_OPTIONS,
  outdir: '.',
  name: 'root',
  description: 'Internal Poetry config to hold development tools for tilediiif',
  version: '0.0.0',
  projectType: ProjectType.UNKNOWN,
  pytest: false,

  deps: [
    "Python@^3.6.6",
  ],
  devDeps: [
    "black@^21.5b2",
    "flake8@^3.9.2",
    "isort@^5.8.0",
    "mypy@^0.812",
  ],
});
rootProject.gitignore.addPatterns('.python-version', '.idea');
rootProject.addTask('test', {
  category: TaskCategory.TEST,
  exec: PROJECT_DIR_NAMES.map(dir => `cd ${dir} && poetry run pytest`).join(' && cd - && '),
})
rootProject.addTask('build-docker-image', {
  category: TaskCategory.BUILD,
  exec: `
  docker image build \\
    --tag camdl/tilediiif.tools:${TILEDIIIF_TOOLS_VERSION} \\
    --build-arg TILEDIIIF_TOOLS_VERSION=${TILEDIIIF_TOOLS_VERSION} \\
    --build-arg TILEDIIIF_CORE_VERSION=${TILEDIIIF_CORE_VERSION} \\
    --target tilediiif.tools .
`,
});
rootProject.addTask('format-python-code', {
  category: TaskCategory.MAINTAIN,
  cwd: __dirname,
  description: '(Re)format Python code using Black',
  exec: `poetry run isort ${PROJECT_PATHS} ; poetry run black ${PROJECT_PATHS} ; poetry run flake8`
});
rootProject.addTask('typecheck-python-code', {
  category: TaskCategory.MAINTAIN,
  cwd: __dirname,
  description: 'Check Python types',
  exec: `poetry run mypy ${PROJECT_PATHS}`,
});


new TextFile(rootProject, '.flake8', {
  lines: `\
; ${PROJEN_MARKER}. To modify, edit .projenrc.js and run "npx projen".
[flake8]
max-line-length = 80
select = C,E,F,W,B,B950
ignore = E203, E501, W503
exclude = .*,__*,dist
`.split('\n')
});

const pyprojectToml = rootProject.tryFindObjectFile('pyproject.toml');
pyprojectToml.addOverride('tool.black.experimental-string-processing', true);
pyprojectToml.addOverride('tool.isort.profile', 'black');
pyprojectToml.addOverride('tool.isort.multi_line_output', 3);


const tilediiifCore = new python.PythonProject({
  ...DEFAULT_OPTIONS,
  parent: rootProject,
  outdir: 'tilediiif.core',
  name: 'tilediiif.core',
  version: TILEDIIIF_CORE_VERSION,

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
  parent: rootProject,
  outdir: 'tilediiif.tools',
  name: 'tilediiif.tools',
  version: TILEDIIIF_TOOLS_VERSION,

  poetryOptions: {
    ...DEFAULT_POETRY_OPTIONS,
    scripts: {
      infojson: 'tilediiif.tools.infojson:main',
      'iiif-tiles': 'tilediiif.tools.tilelayout:main',
      'dzi-tiles': 'tilediiif.tools.dzi_generation_faulthandler:run_dzi_generation_with_faulthandler_enabled',
    },
  },

  deps: [
    "python@^3.7",
    "docopt@^0.6.2",
    "pyvips@^2.1",
    "rfc3986@^1.3",
    `tilediiif.core@=${TILEDIIIF_CORE_VERSION}`,
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
tilediiifToolsPyprojectToml.addOverride('tool.poetry.dev-dependencies.tilediiif\\.core', {path: '../tilediiif.core', develop: true});


const tilediiifServer = new python.PythonProject({
  ...DEFAULT_OPTIONS,
  parent: rootProject,
  outdir: 'tilediiif.server',
  name: 'tilediiif.server',
  version: TILEDIIIF_SERVER_VERSION,

  deps: [
    "python@^3.7",
    "falcon@^2.0",
    `tilediiif.core@=${TILEDIIIF_CORE_VERSION}`,
  ],
  devDeps: [
    "pytest@^6.2.4",
  ],
});
const tilediiifServerPyprojectToml = tilediiifServer.tryFindObjectFile('pyproject.toml');
tilediiifServerPyprojectToml.addOverride('tool.poetry.dependencies.tilediiif\\.core', {path: '../tilediiif.core',  develop: true});


rootProject.synth();
