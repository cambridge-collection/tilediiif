import { default as assert } from "assert";
import "util";
import {
    canonicaliseRequestWithoutDimensions,
    formatImageRequest,
    formatName,
    formatNormalisedNumber,
    formatQuality,
    formatRegion,
    formatRequest,
    formatRotation,
    formatSize,
    ImageInfoRequest,
    ImageQuality,
    ImageRegion,
    ImageRegionType,
    ImageRequest,
    ImageRequestType,
    ImageSize,
    ImageSizeType,
    parseFormat,
    parseName,
    parseQuality,
    parseRegion,
    parseRequest,
    parseRotation,
    parseSize,
    REGION_FULL,
    REGION_SQUARE,
    SIZE_FULL,
    SIZE_MAX,
} from "../src/iiif-image-2.1";

test.each`
    number   | normalised
    ${0}     | ${"0"}
    ${1 / 3} | ${"0.3333333333"}
    ${1.2}   | ${"1.2"}
`(
    "formatNormalisedNumber $number -> $normalised",
    ({ number, normalised }: { number: number; normalised: string }) => {
        expect(formatNormalisedNumber(number)).toBe(normalised);
    }
);

describe("image request", () => {
    describe("region", () => {
        test.each`
            region               | expected
            ${"full"}            | ${REGION_FULL}
            ${"square"}          | ${REGION_SQUARE}
            ${"10,11,12,13"}     | ${{ type: ImageRegionType.ABSOLUTE, x: 10, y: 11, width: 12, height: 13 }}
            ${"pct:10,11,12,13"} | ${{ type: ImageRegionType.RELATIVE, x: 10, y: 11, width: 12, height: 13 }}
        `(
            "parseRegion roundtrip",
            ({
                region,
                expected,
            }: {
                region: string;
                expected: ImageRegion;
            }) => {
                const parsedRegion = parseRegion(region);
                expect(parsedRegion).toEqual(expected);
                expect(formatRegion(parsedRegion!)).toEqual(region);
            }
        );
    });

    describe("size", () => {
        test.each`
            size           | expected
            ${"full"}      | ${SIZE_FULL}
            ${"max"}       | ${SIZE_MAX}
            ${"!10,11"}    | ${{ type: ImageSizeType.BEST_FIT, width: 10, height: 11 }}
            ${"10,11"}     | ${{ type: ImageSizeType.ABSOLUTE, width: 10, height: 11 }}
            ${"10,"}       | ${{ type: ImageSizeType.ABSOLUTE, width: 10, height: undefined }}
            ${",11"}       | ${{ type: ImageSizeType.ABSOLUTE, width: undefined, height: 11 }}
            ${"pct:11"}    | ${{ type: ImageSizeType.RELATIVE, proportion: 11 }}
            ${`pct:1.234`} | ${{ type: ImageSizeType.RELATIVE, proportion: 1.234 }}
        `(
            "parseSize roundtrip",
            ({ size, expected }: { size: string; expected: ImageSize }) => {
                const parsedSize = parseSize(size);
                expect(parsedSize).toEqual(expected);
                expect(formatSize(parsedSize!)).toEqual(size);
            }
        );
    });

    describe("rotation", () => {
        test.each`
            rotation    | expected
            ${"0"}      | ${{ mirrored: false, degrees: 0 }}
            ${"90"}     | ${{ mirrored: false, degrees: 90 }}
            ${"90.99"}  | ${{ mirrored: false, degrees: 90.99 }}
            ${"-1.5"}   | ${{ mirrored: false, degrees: -1.5 }}
            ${"!0"}     | ${{ mirrored: true, degrees: 0 }}
            ${"!90"}    | ${{ mirrored: true, degrees: 90 }}
            ${"!90.99"} | ${{ mirrored: true, degrees: 90.99 }}
            ${"!-1.5"}  | ${{ mirrored: true, degrees: -1.5 }}
        `(
            "parseRotation formatRotation roundtrip",
            ({
                rotation,
                expected,
            }: {
                rotation: string;
                expected: ImageSize;
            }) => {
                const parsedRotation = parseRotation(rotation);
                expect(parsedRotation).toEqual(expected);
                expect(formatRotation(parsedRotation!)).toEqual(rotation);
            }
        );
    });

    describe("quality", () => {
        test.each`
            quality      | expected
            ${"color"}   | ${ImageQuality.COLOR}
            ${"gray"}    | ${ImageQuality.GRAY}
            ${"bitonal"} | ${ImageQuality.BITONAL}
            ${"default"} | ${ImageQuality.DEFAULT}
        `(
            "parse / format roundtrip $quality -> $expected",
            ({
                quality,
                expected,
            }: {
                quality: string;
                expected: ImageSize;
            }) => {
                const parsedQuality = parseQuality(quality);
                expect(parsedQuality).toEqual(expected);
                expect(formatQuality(parsedQuality!)).toEqual(quality);
            }
        );
    });

    describe("format", () => {
        test.each(["jpg", "png", "foo", "JPG", "JpEg", "jp2"])(
            "parseFormat accepts valid formats",
            (format: string) => {
                expect(parseFormat(format)).toEqual(format);
            }
        );
        test.each(["foo.bar", "a b", "foo-bar", ""])(
            "parseFormat rejects invalid formats",
            (format: string) => {
                expect(parseFormat(format)).toBeNull();
            }
        );
    });

    describe("name", () => {
        test.each`
            name             | expected
            ${"color.foo"}   | ${{ quality: ImageQuality.COLOR, format: "foo" }}
            ${"default.jpg"} | ${{ quality: ImageQuality.DEFAULT, format: "jpg" }}
        `(
            'parse / format roundtrip: "$name" -> $expected',
            ({ name, expected }: { name: string; expected: ImageSize }) => {
                const parsedName = parseName(name);
                expect(parsedName).toEqual(expected);
                expect(formatName(parsedName!)).toEqual(name);
            }
        );

        test.each([
            "default.foo.bar",
            "default.a b",
            "deafult.foo-bar",
            "",
            ".jpg",
            "foo.jpg",
        ])("parseName rejects invalid value: %j", (format: string) => {
            expect(parseName(format)).toBeNull();
        });
    });

    describe("parseRequest", () => {
        test.each`
            path                                                           | expected
            ${["ImgId"]}                                                   | ${{ type: ImageRequestType.IMAGE_INFO, identifier: "ImgId", name: undefined }}
            ${["ImgId", ""]}                                               | ${{ type: ImageRequestType.IMAGE_INFO, identifier: "ImgId", name: "" }}
            ${["ImgId", "info.json"]}                                      | ${{ type: ImageRequestType.IMAGE_INFO, identifier: "ImgId", name: "info.json" }}
            ${["ImgId", "full", "full", "0", "default.jpg"]}               | ${{ type: ImageRequestType.IMAGE, identifier: "ImgId", region: REGION_FULL, size: SIZE_FULL, rotation: { degrees: 0, mirrored: false }, quality: ImageQuality.DEFAULT, format: "jpg" }}
            ${["ImgId", "0,0,1024,1024", "512,512", "!90", "bitonal.png"]} | ${{ type: ImageRequestType.IMAGE, identifier: "ImgId", region: { type: ImageRegionType.ABSOLUTE, x: 0, y: 0, width: 1024, height: 1024 }, size: { type: ImageSizeType.ABSOLUTE, width: 512, height: 512 }, rotation: { degrees: 90, mirrored: true }, quality: ImageQuality.BITONAL, format: "png" }}
        `(
            "parse / format roundtrip: $path -> $expected",
            ({
                path,
                expected,
            }: {
                path: string[];
                expected: ImageRequest | ImageInfoRequest;
            }) => {
                const request = parseRequest(path);
                expect(request).toEqual(expected);
                expect(formatRequest(request!)).toEqual(path);
            }
        );

        test.each`
            path
            ${[] as string[]}
            ${[""]}
            ${["", "info.json"]}
            ${"ImgId/foo/full/0/default.jpg".split("/")}
            ${"ImgId/full/foo/0/default.jpg".split("/")}
            ${"ImgId/full/full/foo/default.jpg".split("/")}
            ${"ImgId/full/full/0/dEfaUlt.jpg".split("/")}
            ${"ImgId/full/full/0/default.jPg".split("/")}
        `("does not match invalid path $path", (path: string[]) => {
            expect(parseRequest(path)).toBeNull();
        });
    });

    const UNCHANGED = "**Unchanged**";

    describe("canonicaliseImageRequestWithoutDimensions", () => {
        test.each`
            req                                                                            | expectedCanonicalisation
            ${{ type: ImageRequestType.IMAGE_INFO, identifier: "foo", name: undefined }}   | ${{ type: ImageRequestType.IMAGE_INFO, identifier: "foo", name: "info.json" }}
            ${{ type: ImageRequestType.IMAGE_INFO, identifier: "foo", name: "" }}          | ${{ type: ImageRequestType.IMAGE_INFO, identifier: "foo", name: "info.json" }}
            ${{ type: ImageRequestType.IMAGE_INFO, identifier: "foo", name: "info.json" }} | ${UNCHANGED}
        `(
            "ImageInfoRequest request %req has canonical form $expectedCanonicalisation",
            ({
                req,
                expectedCanonicalisation,
            }: {
                req: ImageInfoRequest;
                expectedCanonicalisation: ImageInfoRequest | typeof UNCHANGED;
            }) => {
                const canonical = canonicaliseRequestWithoutDimensions(req);
                if (expectedCanonicalisation === UNCHANGED) {
                    expect(canonical).toBe(req);
                } else {
                    expect(canonical).toEqual(expectedCanonicalisation);
                }
            }
        );

        test.each`
            req                                              | expectedCanonicalisation
            ${"ImgId/0,0,1000,1000/100,/0/default.jpg"}      | ${UNCHANGED}
            ${"ImgId/0,0,1000,1000/100,100/0/default.jpg"}   | ${"ImgId/0,0,1000,1000/100,/0/default.jpg"}
            ${"ImgId/0,0,1000,1000/,100/0/default.jpg"}      | ${"ImgId/0,0,1000,1000/100,/0/default.jpg"}
            ${"ImgId/pct:0,0,100,100/100,100/0/default.jpg"} | ${UNCHANGED /* Can't canonicalise size against a relative region */}
            ${"ImgId/0,0,100,100/100,/-10/default.jpg"}      | ${"ImgId/0,0,100,100/100,/350/default.jpg"}
            ${"ImgId/0,0,100,100/100,/-370/default.jpg"}     | ${"ImgId/0,0,100,100/100,/350/default.jpg"}
            ${"ImgId/0,0,100,100/100,/360/default.jpg"}      | ${"ImgId/0,0,100,100/100,/0/default.jpg"}
            ${"ImgId/0,0,100,100/100,/370/default.jpg"}      | ${"ImgId/0,0,100,100/100,/10/default.jpg"}
        `(
            "ImageRequest %req has canonical form $expectedCanonicalisation",
            ({
                req,
                expectedCanonicalisation,
            }: {
                req: string;
                expectedCanonicalisation: string;
            }) => {
                const parsedReq = parseRequest(req.split("/"));
                assert(parsedReq?.type === ImageRequestType.IMAGE);

                const canonical =
                    canonicaliseRequestWithoutDimensions(parsedReq);

                if (expectedCanonicalisation === UNCHANGED) {
                    expect(canonical).toBe(parsedReq);
                } else {
                    expect(formatImageRequest(canonical).join("/")).toEqual(
                        expectedCanonicalisation
                    );
                }
            }
        );
    });
});
