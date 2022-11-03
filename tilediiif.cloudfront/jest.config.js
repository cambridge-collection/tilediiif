/** @type {import('ts-jest').JestConfigWithTsJest} */
module.exports = {
  // preset: "ts-jest",
  testEnvironment: "node",
  testMatch: ["**/tests/**/*.ts"],
  transform: {
    "tests/.*.ts$": [
      "ts-jest",
      {
        tsconfig: "./tests/tsconfig.json",
      },
    ],
    "src/.*.ts$": [
      "ts-jest",
      {
        tsconfig: "./src/tsconfig.json",
      },
    ],
  },
};
