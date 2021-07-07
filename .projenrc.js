const { python, ProjectType, TextFile, TextFileOptions, JsonFile, JsonFileOptions, Project, IniFile, ObjectFile } = require('projen');
const { PROJEN_MARKER } = require('projen/lib/common');
const fsp = require('fs/promises');
const fs = require('fs');
const path = require('path');
const { DependencyType } = require('projen/lib/deps');
const { JobPermission } = require('projen/lib/github/workflows-model');
const { Component } = require('projen/lib/component');
const { PythonProject } = require('projen/lib/python');
const assert = require('assert');
const { GithubWorkflow } = require('projen/lib/github');

const DEV_ENVIRONMENT_IMAGE = 'ghcr.io/cambridge-collection/tilediiif/dev-environment:v0.1.4-tools'

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

const DEFAULT_VERSION = '0.1.0';


class RootProject extends Project {
  constructor(options) {
    super(options);

    this.gitignore.addPatterns('.python-version', '.idea', '*.iml', '.vscode');

    this.testTask = this.addTask('test', {
      description: 'Run tests for tilediiif.* packages.'
    });
    this.typecheckTask = this.addTask('typecheck-python', {
      description: 'Check Python types for tilediiif.* packages.',
    });
    this.formatPythonTask = this.addTask('format-python-code', {
      description: 'Format Python code of tilediiif.* packages.',
    });
    this.ciSetupTask = this.addTask('ci:setup', {
      description: 'Prepare the checked out project for running CI tasks without running a projen synth, e.g. install dependencies',
    });
  }
}

/**
 * Causes `poetry install` to be run when synthesizing a Poetry Python project.
 *
 * By default only `poetry update` is run, which doesn't make the project's
 * script commands available for execution in a shell.
 */
class PoetryInstallAction extends Component {
  /**
   * @param {PythonProject} project
   */
  constructor(project) {
    super(project);
    const installTask = project.tasks.tryFind('install');
    if(!installTask) {
      throw new Error(`project has no 'install' task`);
    }

    installTask.exec('poetry install');
  }
}

/**
 * @typedef {Object} GetOrCreateJsonFileResult
 * @property {ObjectFile} objectFile
 * @property {Object} content
 *
 * @param {Project} project
 * @param {Object} options
 * @param {string} options.filePath
 * @param {Object} [options.initialContent]
 * @param {JsonFileOptions} [options.jsonFileOptions] options to use if a JsonFile needs to be created
 * @returns {GetOrCreateJsonFileResult}
 */
function getOrCreateJsonFile(project, {filePath, initialContent, jsonFileOptions}) {
  let existingContent = undefined;
  try {
    existingContent = fs.readFileSync(filePath, {encoding: 'utf-8'});
  }
  catch(e) {}
  const content = existingContent ? JSON.parse(existingContent) : (initialContent ?? {});

  const objectFile = project.tryFindObjectFile(filePath);
  if(objectFile) {
    return {objectFile, content};
  }

  return {
    objectFile: new JsonFile(project, filePath, {
      obj: content,
      ...(jsonFileOptions ?? {
        marker: false,
        readonly: false,
      }),
    }),
    content,
  };
}

class StandardVersionPackageJson extends Component {
  /**
   * @param {Project} project
   * @param {Object} options
   * @param {string} options.directoryPath
   * @param {ObjectFile} options.versionFile
   * @param {string} options.version
   */
  constructor(project, {directoryPath, version}) {
    super(project);
    const projenRootPath = path.relative(directoryPath, '.');
    const {objectFile: versionFile} = getOrCreateJsonFile(project, {filePath: path.join(directoryPath, 'package.json')});
    versionFile.addOverride('version', version);
    versionFile.addOverride('standard-version', {
      scripts: {
        // re-synth projen to update things referencing version numbers
        postchangelog: `(cd ${projenRootPath} && npx projen && git add .)`,
      }
    });
  }
}

function getJsonFileContent(filePath, defaultContent) {
  if(defaultContent !== undefined && !fs.existsSync(filePath)) {
    return defaultContent;
  }
  try {
    return JSON.parse(fs.readFileSync(filePath, {encoding: 'utf-8'}));
  } catch(e) {
    throw new Error(`Unable to parse JSON file (filePath: ${filePath}, error: ${e})`);
  }
}

/**
 * Maintain a semver version number for a directory.
 *
 * The version number is stored in a package.json file, and a summary of version
 * changes in a CHANGELOG.md. Both are automatically updated based on commits
 * touching the directory which follow the conventional-commits format.
 *
 * A create-release:<name> projen task invokes standard-version to update the
 * package.json and CHANGELOG.md.
 *
 * @typedef {Object} StandardVersionedDirectoryOptions
 * @property {string} directoryPath
 * @property {string} [version]
 */
class StandardVersionedDirectory extends Component {
  /**
   * @param {string} directoryPath
   * @param {string} [defaultVersion]
   * @returns {string}
   */
  static getVersion(directoryPath, defaultVersion = DEFAULT_VERSION) {
    const versionFilePath = path.join(directoryPath, 'package.json');
    const version = getJsonFileContent(versionFilePath, {}).version;
    if(typeof version === 'string' && /\w/.test(version)) {
      return version;
    }
    return defaultVersion;
  }

  constructor(project, {name, directoryPath, version, tagName}) {
    super(project);
    tagName = tagName ?? name;
    version = version ?? StandardVersionedDirectory.getVersion(directoryPath);
    new StandardVersionPackageJson(project, {directoryPath, version});

    project.addTask(`create-release:${name}`, {
      cwd: directoryPath,
      description: `Generate a tagged release commit for ${name} using standard-version`,
      condition: 'test "$(git status --porcelain)" == ""',
      exec: `\
npx standard-version --commit-all --path . --tag-prefix "${tagName}-v" \\
  --releaseCommitMessageFormat "chore(release): ${tagName}-v{{currentTag}}"`
    });

    this.version = version;
  }
}

class TilediiifProject extends python.PythonProject {
  /**
   * @param {Project} rootProject
   * @param {string} name
   * @param {import('projen/python').PythonProjectOptions} options
   */
  constructor(rootProject, name, {testPackages, deps, devDeps, ...options}) {
    const version =  StandardVersionedDirectory.getVersion(name);

    super({
      ...DEFAULT_OPTIONS,
      parent: rootProject,
      outdir: name,
      name,
      moduleName: name,
      version,
      ...options,
    });

    this.relativeOutdir = path.relative(rootProject.outdir, this.outdir);

    // run `poetry install` during synth to make project scripts executable on $PATH
    new PoetryInstallAction(this);

    // The Python project defines several dependencies automatically which we
    // need to override. e.g. it depends on Python ^3.6, but black requires
    // a slightly more specific version of 3.6, which fails unless we replace
    // the default Python@^3.6 dep.
    this._overrideDependencies({deps, devDeps});
    this.addDevDependency("black@^21.6b0");
    this.addDevDependency("flake8@^3.9.2");
    this.addDevDependency("isort@^5.8.0");
    this.addDevDependency("mypy@^0.901");

    this.testPackages = [...(testPackages || [])];

    new StandardVersionedDirectory(rootProject, {
      name,
      directoryPath: this.relativeOutdir,
      version,
    });

    this.ensureReleaseableTask = rootProject.addTask(`ensure-checkout-is-releaseable:${name}`, {
      description: `Fail with an error if the working copy is not a clean checkout of a ${name} release tag.`,
      exec: `\
        test "$(git rev-parse HEAD)" == "$(git rev-parse tags/${name}-v${this.version}^{commit})" \\
          && test "$(git status --porcelain)" == "" \\
          || (echo "Error: the git checkout must be clean and tagged as ${name}-v${this.version}" 1>&2; exit 1)
      `,
    });

    rootProject.typecheckTask.spawn(rootProject.addTask(`typecheck-python:${name}`, {
      description: `Typecheck ${name} with mypy`,
      exec: `\\
        cd "${this.relativeOutdir}" \\
        && poetry run mypy --namespace-packages \\
          -p ${name} \\
          ${this.testPackages.map(p => `-p ${p}`).join(' ')}`
    }));
    rootProject.ciSetupTask.exec(`\
cd "${this.relativeOutdir}" \\
&& poetry install`);

    new IniFile(this, 'mypy.ini', {
      obj: {
        mypy: {
          exclude: '/dist/'
        }
      }
    });

    rootProject.formatPythonTask.spawn(rootProject.addTask(`format-python-code:${name}`, {
      description: `Format Python code of ${name}.`,
      exec: `cd "${this.relativeOutdir}" && poetry run isort . ; poetry run black . ; poetry run flake8`
    }));
    const pyprojectToml = this.tryFindObjectFile('pyproject.toml');
    pyprojectToml.addOverride('tool.black.experimental-string-processing', true);
    pyprojectToml.addOverride('tool.isort.profile', 'black');
    pyprojectToml.addOverride('tool.isort.multi_line_output', 3);
    new TextFile(this, '.flake8', {
      lines: `\
    ; ${PROJEN_MARKER}. To modify, edit .projenrc.js and run "npx projen".
    [flake8]
    max-line-length = 80
    select = C,E,F,W,B,B950
    ignore =
      # the default "line too long" warning. Disabled because flake8-bugbear has its
      # own more permissive version.
      E501,

      # "line break before binary operator", black violates this
      W503,

      # "whitespace before ':'", black violates this when formatting slices
      E203,

      # flake8-bugbear warning about using the result of function calls for arg defaults.
      # Hypothesis uses this a lot, it's only a problem if the returned value is mutable.
      B008
    exclude = .*,__*,dist
    `.split('\n')
    });

    rootProject.testTask.spawn(rootProject.addTask(`test:${name}`, {
      exec: `cd "${this.relativeOutdir}" && poetry run pytest`
    }));

    // this.buildWorkflow = this._createBuildWorkflow(rootProject.github);
    // this.releaseWorkflow = rootProject.github.addWorkflow(`build-${name}`);
  }

  _createBuildWorkflow(github) {
    const workflow = github.addWorkflow(`build-${this.moduleName}`);

    workflow.on({
      pullRequest: { }
    });

    workflow.addJobs({
      build: {
        permissions: {
          contents: JobPermission.READ
        },
        runsOn: 'ubuntu-latest',
        steps: [
          { name: 'Checkout', uses: 'actions/checkout@v2' },
          {  }
        ]
      }
    })



    return workflow;
  }

  _overrideDependencies({deps, devDeps}) {
    [
      ...(deps || []).map(d => [d, DependencyType.RUNTIME]),
      ...(devDeps || []).map(d => [d, DependencyType.DEVENV]),
    ].forEach(([depSpec, type]) => {
      const [depName] = depSpec.split('@', 1);
      // Remove conflicting dependencies defined by the default Python project
      try {
        this.deps.getDependency(depName, type);
        this.deps.removeDependency(depName, type);
      } catch(e) {}
      this.deps.addDependency(depSpec, type);
    });
  }
}

/**
 * Create a dockerfile containing the concatenation of multiple dockerfiles.
 *
 * @param {Project} project
 * @param {string} filePath
 * @param {Array<string>} fragmentPaths The paths of files to concatenate.
 * @param {TextFileOptions} [textFileOptions]
 * @returns {Promise<TextFile>}
 */
async function dockerfileFromFragments(project, filePath, fragmentPaths, textFileOptions) {
  const loadedFragments = await Promise.all(
    fragmentPaths.map(async p => ({
      path: p,
      content: splitDockerfileGlobalArgs(await fsp.readFile(p, {encoding: 'utf-8'})),
    })));

    return new TextFile(project, filePath, {
    editGitignore: false,
    ...(textFileOptions ?? {}),
    lines: [
      `# ${PROJEN_MARKER}. To modify, edit .projenrc.js and run "npx projen".`,
      ...[
        // global ARG section of all fragments
        ...loadedFragments.flatMap(({path, content}) => content.head ? [
          '',
          `# header: ${path}`,
          content.head.trim(),
        ] : []),
        // bodies of all fragments
        ...loadedFragments.flatMap(({path, content}) => [
          '',
          `# body: ${path}`,
          content.body.trim(),
        ]),
      ].slice(1),
    ],
  });
}

/**
 * Split a dockerfile in two at the start of the first "FROM ..." line.
 *
 * @typedef {Object} ParsedDockerfile
 * @property {string} head The portion before the FROM ...
 * @property {string} body The portion starting from the first FROM ...
 *
 * @param {string} dockerfile The text of the Dockerfile to split
 * @returns {ParsedDockerfile} The head (containing any global ARG lines), and
 *    the rest of the file.
 */
function splitDockerfileGlobalArgs(dockerfile) {
  const {index} = (/(?<=^\s*)FROM\b/m).exec(dockerfile)
  return {
    head: dockerfile.slice(0, index ?? 0),
    body: dockerfile.slice(index ?? 0),
  };
}

/**
 * @typedef {Object} DockerImageTargetOptions
 * @property {string} [target]
 * @property {string | string[]} tag
 * @param {Object<string, string>} [buildArgs]
 * @param {Object<string, string>} [labels]
 */

/**
 * @typedef {Object} DockerImageOptions
 * @param {string} options.directoryPath The path of the Dockerfile's directory.
 * @param {string} options.contextPath The path to use as the build context. Can reference environment variables
 *   `$GIT_DIR` and `$VERSION_CHECKOUT`. Default value: `$VERSION_CHECKOUT`.
 * @param {string} options.version The version of the image.
 * @param {string} options.nickName A short name for the image, used to form projen task names
 * @param {string} options.imageName The part before the : of the image name.
 * @param {Array<DockerImageTargetOptions>} targets
 */

/**
 * @callback DockerImageCreateCb
 * @param {string} version
 * @returns {DockerImageOptions}
 */

/**
 * Build and publish docker images from a Dockerfile.
 */
class DockerImage extends Component {
  /**
   *
   * @param {Project} project
   * @param {DockerImageOptions} options
   * @param {DockerImageCreateCb} optionsCallback
   * @returns {Promise<DockerFile>}
   */
  static createWithVersion(project, options, optionsCallback) {
    optionsCallback = optionsCallback ?? ((options) => options);
    const version = StandardVersionedDirectory.getVersion(options.directoryPath);
    return new DockerImage(project, {...(optionsCallback({...options, version}))});
  }

  /**
   * @param {Project} project
   * @param {DockerImageOptions} options
   */
  constructor(project, {directoryPath, contextPath, version, nickName, imageName, targets}) {
    super(project);
    targets = targets.map(({target, tag, buildArgs, labels}) => ({
      target,
      tag: typeof tag === 'string' ? [tag] : [...tag],
      buildArgs: buildArgs ?? {},
      labels: {
        'org.opencontainers.image.version': version,
        'org.opencontainers.image.revision': '$(git rev-parse --verify HEAD)',
        ...(labels ?? {})
      }
    }));
    const dockerfilePath = path.join(directoryPath, 'Dockerfile');

    new StandardVersionedDirectory(project, {
      name: `docker:${nickName}`,
      tagName: `docker/${nickName}`,
      directoryPath,
      version,
    });
    // the git revision the image is built from
    const commitIsh = `docker/${nickName}-v${version}`;

    const buildCommands = targets.map(({target, tag, buildArgs, labels}) => {
      tag = typeof tag === 'string' ? [tag] : Array.from(tag);

      const tagArguments = tag.map(t => `--tag "${imageName}:${t}"`).join(' ');
      const buildArgArguments = Object.entries(buildArgs)
        .map(([n, v]) => `--build-arg "${n}=${v}"`).join(' ');
      const labelArguments = Object.entries(labels)
        .map(([n, v]) => `--label "${n}=${v}"`).join(' ');

        return `\
&& docker image build \\
  --file "${dockerfilePath}" \\
  ${tagArguments} \\
  ${buildArgArguments} \\
  ${labelArguments} \\
  ${target ? `--target "${target}"` : ''} \\
  "${contextPath ?? '$VERSION_CHECKOUT'}"`;
    }).join(' \\\n');

    const fullImageNames = targets.flatMap(target => target.tag.map(tag => `${imageName}:${tag}`));
    const notAllTagsExist = `! docker image inspect ${fullImageNames.join(' ')} > /dev/null 2>&1`;

    this.buildTask = project.addTask(`build-docker-image:${nickName}`, {
      condition: notAllTagsExist,
      env: {
        GIT_DIR: '$(git rev-parse --git-common-dir)',
        VERSION_CHECKOUT: '$(mktemp -d)',
      },
      exec: `\
git worktree add --detach "$VERSION_CHECKOUT" "${commitIsh}" \\
&& cd "$VERSION_CHECKOUT" \\
${buildCommands} \\
&& cd - \\
&& git worktree remove "$VERSION_CHECKOUT"`,
    });

    this.pushTask = project.addTask(`push-docker-image:${nickName}`, {
    });
    this.pushTask.prependSpawn(this.buildTask);
    fullImageNames.forEach(image => this.pushTask.exec(`docker image push ${image}`));

    this.releaseWorkflow = DockerImage.createReleaseWorkflow({
      github: project.github,
      nickName,
    });
  }

  static createReleaseWorkflow({github, nickName}) {
    const workflow = new GithubWorkflow(github, `release-docker-image-${nickName}`);
    workflow.on({
      push: {
        tags: [`docker/${nickName}-v*`],
      },
    });

    workflow.addJobs({
      release: {
        permissions: {
          contents: JobPermission.READ,
          packages: JobPermission.WRITE,
        },
        runsOn: 'ubuntu-latest',
        container: {
          image: DEV_ENVIRONMENT_IMAGE,
          credentials: {
            username: '${{ github.actor }}',
            password: '${{ secrets.GITHUB_TOKEN }}',
          },
        },
        defaults: {
          run: {
            shell: 'bash',
          },
        },
        steps: [
          { uses: 'actions/checkout@v2', },
          { run: `npx projen build-docker-image:${nickName}`, },
          { run: `npx projen push-docker-image:${nickName}`, },
        ],
      },
    });

    return workflow;
  }
}

/**
 * Split a semver verison number into 3 decreasingly-specific version strings.
 *
 * @param {string} version A semver version, e.g. 1.2.3 or 1.2.3-foo+bar
 * @returns {Array<string>} The version with 0, 1 and 2 right-most components excluded.
 * @example splitSemverComponents('1.2.3') // ['1.2.3', '1.2', '1']
 */
function splitSemverComponents(version) {
  const match = /(\d+)\.(\d+)\.(\d+)/.exec(version);
  if(!match) {
    throw new Error(`Unable to parse version: ${version}`);
  }
  const numbers = match.slice(1, 4);
  return [3, 2, 1].map(count => numbers.slice(0, count).join('.'));
}

async function constructProject() {
  const rootProject = new RootProject({
    ...DEFAULT_OPTIONS,
    outdir: '.',
    name: 'root',
    description: 'Internal Poetry config to hold development tools for tilediiif',
    version: '0.0.0',
    projectType: ProjectType.UNKNOWN,
    pytest: false,
    mergify: true,
    stale: false,

    deps: [],
    devDeps: [],
  });

  const tilediiifCore = new TilediiifProject(rootProject, 'tilediiif.core', {
    testPackages: ['tests'],
    deps: [
      "docopt@^0.6.2",
      "jsonpath-rw@^1.4",
      "jsonschema@^3.0",
      "python@^3.7",
      "toml@^0.10.0",
    ],
    devDeps: [
      "hypothesis@^4.36",
      "pytest@^6.2.4",
      "types-pkg_resources@^0.1.2",
      "types-pytz@^0.1.0",
      "types-toml@^0.1.1",
    ],
  });
  const tilediiifCorePyprojectToml = tilediiifCore.tryFindObjectFile(`pyproject.toml`);
  tilediiifCorePyprojectToml.addOverride('tool.poetry.packages', [{include: 'tilediiif'}]);


  const tilediiifTools = new TilediiifProject(rootProject, 'tilediiif.tools', {
    testPackages: ['tests', 'integration_tests'],
    poetryOptions: {
      ...DEFAULT_POETRY_OPTIONS,
      scripts: {
        infojson: 'tilediiif.tools.infojson:main',
        'iiif-tiles': 'tilediiif.tools.tilelayout:main',
        'dzi-tiles': 'tilediiif.tools.dzi_generation_faulthandler:run_dzi_generation_with_faulthandler_enabled',
      },
    },

    deps: [
      "docopt@^0.6.2",
      "python@^3.7",
      "pyvips@^2.1",
      "rfc3986@^1.3",
      `tilediiif.core@=${tilediiifCore.version}`,
    ],
    devDeps: [
      "flake8-bugbear@^19.8",
      "httpie@^1.0",
      "hypothesis@^4.36",
      "ipython@^7.8",
      "numpy@^1.17",
      "pytest-lazy-fixture@^0.6.1",
      "pytest-subtesthack@0.1.1",
      "pytest@^6.2.4",
      "toml@^0.10.0",
      "tox@^3.14",
      "yappi@^1.0",
    ],
  });

  const tilediiifToolsPyprojectToml = tilediiifTools.tryFindObjectFile('pyproject.toml');
  tilediiifToolsPyprojectToml.addOverride('tool.poetry.dev-dependencies.tilediiif\\.core', {path: '../tilediiif.core', develop: true});

  const tilediiifToolsVersionModule = new TextFile(tilediiifTools, 'tilediiif/tools/version.py', {
    lines: [
      `# ${PROJEN_MARKER}`,
      `__version__ = "${tilediiifTools.version}"`,
      '',
    ],
    editGitignore: false,
  });


  const tilediiifServer = new TilediiifProject(rootProject, 'tilediiif.server', {
    testPackages: ['tests'],
    deps: [
      "falcon@^2.0",
      "python@^3.7",
      `tilediiif.core@=${tilediiifCore.version}`,
    ],
    devDeps: [
      "pytest@^6.2.4",
    ],
  });
  const tilediiifServerPyprojectToml = tilediiifServer.tryFindObjectFile('pyproject.toml');
  tilediiifServerPyprojectToml.addOverride('tool.poetry.dependencies.tilediiif\\.core', {path: '../tilediiif.core',  develop: true});

  const dockerfileFragments = Object.fromEntries(Object.entries({
    base: 'base',
    buildMozjpeg: 'build-mozjpeg',
    buildTilediiifWheelBase: 'build-tilediiif-wheel-base',
    buildTilediiifCoreWheel: 'build-tilediiif.core-wheel',
    buildTilediiifToolsWheel: 'build-tilediiif.tools-wheel',
    buildVips: 'build-vips',
    dev: 'dev',
    pythonBase: 'python-base',
    tilediiifToolsParallel: 'tilediiif.tools-parallel',
    tilediiifTools: 'tilediiif.tools',
  }).map(([key, name]) => [key, path.join('docker/fragments', `${name}.Dockerfile`)]));

  const dockerFiles = {
    dev: await dockerfileFromFragments(rootProject, 'docker/images/dev/Dockerfile', [
      dockerfileFragments.buildMozjpeg,
      dockerfileFragments.buildVips,
      dockerfileFragments.pythonBase,
      dockerfileFragments.base,
      dockerfileFragments.dev,
    ]),
    tilediiifTools: await dockerfileFromFragments(rootProject, 'docker/images/tilediiif.tools-slim/Dockerfile', [
      dockerfileFragments.buildMozjpeg,
      dockerfileFragments.buildVips,
      dockerfileFragments.pythonBase,
      dockerfileFragments.base,
      dockerfileFragments.buildTilediiifWheelBase,
      dockerfileFragments.buildTilediiifCoreWheel,
      dockerfileFragments.buildTilediiifToolsWheel,
      dockerfileFragments.tilediiifTools,
    ]),
    tilediiifToolsParallel: await dockerfileFromFragments(rootProject, 'docker/images/tilediiif.tools-parallel/Dockerfile', [
      dockerfileFragments.buildMozjpeg,
      dockerfileFragments.buildVips,
      dockerfileFragments.pythonBase,
      dockerfileFragments.base,
      dockerfileFragments.buildTilediiifWheelBase,
      dockerfileFragments.buildTilediiifCoreWheel,
      dockerfileFragments.buildTilediiifToolsWheel,
      dockerfileFragments.tilediiifTools,
      dockerfileFragments.tilediiifToolsParallel,
    ]),
  };

  const {content: toolsSlimImagePkgJson} = getOrCreateJsonFile(rootProject, {
    filePath: 'docker/images/tilediiif.tools-slim/package.json',
    jsonFileOptions: {
      marker: false,
      readonly: false,
    }
  });
  assert((toolsSlimImagePkgJson.tilediiif ?? {}).toolsVersion);
  assert((toolsSlimImagePkgJson.tilediiif ?? {}).coreVersion);
  DockerImage.createWithVersion(rootProject, {
    directoryPath: 'docker/images/tilediiif.tools-slim',
  }, ({version, ...options}) => ({
    ...options,
    contextPath: '$GIT_DIR',
    version,
    nickName: 'tilediiif.tools-slim',
    imageName: 'ghcr.io/cambridge-collection/tilediiif.tools',
    targets: [
      {
        tag: [
          // Tag separately for tools version and image version
          ...splitSemverComponents(tilediiifTools.version).map(ver => `v${ver}-slim`),
          ...splitSemverComponents(version).map(ver => `image-v${ver}-slim`),
        ],
        buildArgs: {
          // FIXME: need to pull the version from the docker/images/* dir so that changes are noticed by standard-version
          TILEDIIIF_TOOLS_SHA: `tags/tilediiif.tools-v${toolsSlimImagePkgJson.tilediiif.toolsVersion}`,
          TILEDIIIF_CORE_SHA: `tags/tilediiif.core-v${toolsSlimImagePkgJson.tilediiif.coreVersion}`,
        },
        labels: {
          'org.opencontainers.image.title': 'tilediiif.tools slim',
          'org.opencontainers.image.description': 'The tilediiif.tools Python package.',
          'org.opencontainers.image.version': `${version} (tilediiif.tools=${toolsSlimImagePkgJson.tilediiif.toolsVersion}, tilediiif.core=${toolsSlimImagePkgJson.tilediiif.coreVersion})`,
        },
      }
    ],
  }));

  const {content: toolsParallelImagePkgJson} = getOrCreateJsonFile(rootProject, {
    filePath: 'docker/images/tilediiif.tools-parallel/package.json',
    jsonFileOptions: {
      marker: false,
      readonly: false,
    }
  });
  assert.strictEqual((toolsParallelImagePkgJson.tilediiif ?? {}).toolsVersion, toolsSlimImagePkgJson.tilediiif.toolsVersion);
  assert.strictEqual((toolsParallelImagePkgJson.tilediiif ?? {}).coreVersion, toolsSlimImagePkgJson.tilediiif.coreVersion);
  DockerImage.createWithVersion(rootProject, {
    directoryPath: 'docker/images/tilediiif.tools-parallel',
  }, ({version, ...options}) => ({
    ...options,
    contextPath: '$GIT_DIR',
    version,
    nickName: 'tilediiif.tools-parallel',
    imageName: 'ghcr.io/cambridge-collection/tilediiif.tools',
    targets: [
      {
        tag: [
          // Tag separately for tools version and image version
          ...splitSemverComponents(tilediiifTools.version).map(ver => `v${ver}`),
          ...splitSemverComponents(version).map(ver => `image-v${ver}`),
        ],
        buildArgs: {
          TILEDIIIF_TOOLS_SHA: `tags/tilediiif.tools-v${toolsParallelImagePkgJson.tilediiif.toolsVersion}`,
          TILEDIIIF_CORE_SHA: `tags/tilediiif.core-v${toolsParallelImagePkgJson.tilediiif.coreVersion}`,
        },
        labels: {
          'org.opencontainers.image.title': 'tilediiif.tools parallel',
          'org.opencontainers.image.description': 'The tilediiif.tools Python package, plus GNU parallel.',
          'org.opencontainers.image.version': `${version} (tilediiif.tools=${toolsParallelImagePkgJson.tilediiif.toolsVersion}, tilediiif.core=${toolsParallelImagePkgJson.tilediiif.coreVersion})`,
        },
      }
    ],
  }));

  DockerImage.createWithVersion(rootProject, {
    directoryPath: 'docker/images/dev',
  }, ({version, ...options}) => ({
    ...options,
    version,
    nickName: 'tilediiif-dev',
    imageName: 'ghcr.io/cambridge-collection/tilediiif/dev-environment',
    targets: [
      {
        target: 'tools-dev',
        tag: [
          ...splitSemverComponents(version).map(ver => `v${ver}-tools`),
        ],
        labels: {
          'org.opencontainers.image.title': 'tilediiif-dev-env',
          'org.opencontainers.image.title': 'tilediiif development environment.',
        }
      },
      {
        target: 'tools-dev',
        tag: [
          ...splitSemverComponents(version).map(ver => `v${ver}-tools-without-mozjpeg`),
        ],
        buildArgs: {
          VIPS_USE_MOZJPEG: '',
        },
        labels: {
          'org.opencontainers.image.title': 'tilediiif-dev-env (without mozjpeg)',
          'org.opencontainers.image.title': 'tilediiif development environment (without mozjpeg installed).',
        }
      },
      {
        target: 'tools-dev-with-broken-mozjpeg',
        tag: [
          ...splitSemverComponents(version).map(ver => `v${ver}-tools-with-broken-mozjpeg`),
        ],
        labels: {
          'org.opencontainers.image.title': 'tilediiif-dev-env (broken mozjpeg)',
          'org.opencontainers.image.description': 'tilediiif development environment (with vips built for mozjpeg, but mozjpeg unavailable).',
        }
      },
    ],
  }));

  const toolsDockerImageName = 'camdl/tilediiif.tools'
  const toolsReleaseDockerImages = [
    {name: 'slim', target: 'tilediiif.tools', tag: `${tilediiifTools.version}-slim`},
    {name: 'default', target: 'tilediiif.tools-parallel', tag: tilediiifTools.version},
  ]

  return rootProject;
}

(async() => { (await constructProject()).synth(); })().catch(e => {
  console.error(e);
  process.exit(1);
});
