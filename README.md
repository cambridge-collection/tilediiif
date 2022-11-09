# tilediiif

## Developing — Docker Images

It's not obvious how to test Dockerfile changes while making changes to them in
development because the Docker images created by
`npx projen build-docker-image:xxx` use a fixed build context from a git tag.

To test them without tagging and releasing changes, run a command such as this:

```console
$ BUILDKIT_PROGRESS=plain docker image build \
    --file docker/images/tilediiif.awslambda/Dockerfile \
    --target=tilediiif.awslambda \
    --build-arg TILEDIIIF_CORE_SHA=origin/docker-debug \
    --build-arg TILEDIIIF_TOOLS_SHA=origin/docker-debug \
    --build-arg TILEDIIIF_AWSLAMBDA_SHA=origin/docker-debug \
    .git
```

-   The build context is the .git directory — it's the git repo
-   The build still need to check out a version to build from. In this example I
    have the `docker-debug` branch checked out, and am committing to it when
    making changes that need rebuilding. Changes to the Dockerfile itself don't
    need to be committed, only changes to files that are used in the build
    context.
-   It can help to use `SHELL ["bash", "-exc"]` in the Dockerfile to enable the
    `-x` option, which causes bash to print the exact commands its running.
