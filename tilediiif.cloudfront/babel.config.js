module.exports = {
  presets: [
    // This doesn't typecheck the code, so we still need to run tsc to do that.
    // "@babel/preset-typescript",
    [
      "@babel/preset-env",
      {
        // CloudFront Functions supports a slightly unusual set of javascript
        // features. ES5 plus a few select features from more recent standards.
        // Node 0.12 is roughly ES5, so we base on that and exclude transforms
        // for features that are supported by CloudFront Functions and therefore
        // do not need transpiling.
        targets: {
          node: "0.12",
        },
        exclude: [
          "@babel/plugin-transform-exponentiation-operator",
          "@babel/plugin-transform-template-literals",
          "@babel/plugin-transform-arrow-functions",
          "@babel/plugin-transform-parameters",
        ],
        // Rollup bundles everything into a single file for us, no need to do
        // anything else.
        modules: false,
      },
    ],
  ],
  // We use terser to minify separately
  minified: false,
};
