import typescript from "@rollup/plugin-typescript";

export default {
    input: "src/index.ts",
    output: {
        dir: "output/rollup",
        // We wrap everything in a function and assign to `handler`, which is
        // the fixed entry point use by CloudFront Functions to call our code.
        format: "iife",
        name: "handler",
        // CloudFront Functions are in strict mode by default
        strict: false,
    },
    plugins: [
        typescript({
            tsconfig: "src/tsconfig.json",
            compilerOptions: {
                outDir: "output/rollup/typescript",
            },
        }),
    ],
};
