# `tilediiif` CloudFront

This directory contains`tilediiif`'s CloudFront integration. We use CloudFront
Functions (basically JavaScript-only ligher-weight Lambda functions) to
implement:

-   IIIF Image API request canonicalisation
-   Mapping IIIF Image API requests to S3 bucket locations of pre-generated
    tiles

## Build

CloudFront Functions imposes quite strict limits on code size (10KB max), and
supports an unusual subset of JavaScript features. We use a combination of
rollup, babel and terser to build a single, compact JavaScript file from the
TypeScript sources.

1.  rollup: Bundles ES modules into a single file, while eliminating dead/unused
    code. It also strips off TypeScript type annotations.

    It's perfect for CloudFront function modules, as it's able to merge ES
    modules without wrapping them with a bulky module isolation/loading system.
    So the minified code is basically as small as if it had been hand written
    without modules.

2.  babel: Transforms the single file produced by rollup to transpile JS
    features not supported by the CloudFront Functions runtime
3.  terser: Minifies the babel output, to optimise the final code size.

To run the build, use `$ npm run build`.
