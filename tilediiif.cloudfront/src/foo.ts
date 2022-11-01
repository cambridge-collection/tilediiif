export function foo(thing: number): string {
    bar("foo", "bar", "\u1234", `${thing}`);
    const x = Object.freeze({ a: 2 });
    return `${thing ** 2}-foo-${x}`;
}

export const bar = (...args: string[]) => {
    console.log(...[...args]);
};
