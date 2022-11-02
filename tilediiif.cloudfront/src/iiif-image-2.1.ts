import { info } from "console";

export enum ImageRequestType {
    IMAGE_INFO,
    IMAGE,
}

export interface ImageInfoRequest {
    type: ImageRequestType.IMAGE_INFO;
    identifier: string;
    name: undefined | "" | "info.json";
}

export interface ImageRequest {
    type: ImageRequestType.IMAGE;
    identifier: string;
    region: ImageRegion;
    size: ImageSize;
    rotation: ImageRotation;
    quality: ImageQuality;
    format: string;
}

export type ImageRegion =
    | NamedImageRegion
    | RelativeImageRegion
    | AbsoluteImageRegion;

export enum ImageRegionType {
    NAMED,
    ABSOLUTE,
    RELATIVE,
}

export interface NamedImageRegion {
    type: ImageRegionType.NAMED;
    name: "full" | "square";
}

export const REGION_FULL: NamedImageRegion = {
    type: ImageRegionType.NAMED,
    name: "full",
};
export const REGION_SQUARE: NamedImageRegion = {
    type: ImageRegionType.NAMED,
    name: "square",
};

export interface RelativeImageRegion {
    type: ImageRegionType.RELATIVE;
    x: number;
    y: number;
    width: number;
    height: number;
}

export interface AbsoluteImageRegion {
    type: ImageRegionType.ABSOLUTE;
    x: number;
    y: number;
    width: number;
    height: number;
}

export type ImageSize =
    | NamedImageSize
    | RelativeImageSize
    | AbsoluteImageSize
    | BestFitImageSize;

export enum ImageSizeType {
    NAMED,
    RELATIVE,
    ABSOLUTE,
    BEST_FIT,
}

export interface NamedImageSize {
    type: ImageSizeType.NAMED;
    name: "full" | "max";
}

export const SIZE_FULL: NamedImageSize = {
    type: ImageSizeType.NAMED,
    name: "full",
};

export const SIZE_MAX: NamedImageSize = {
    type: ImageSizeType.NAMED,
    name: "max",
};

export interface RelativeImageSize {
    type: ImageSizeType.RELATIVE;
    proportion: number;
}

export type AbsoluteImageSize = { type: ImageSizeType.ABSOLUTE } & (
    | { width: number; height: undefined }
    | { width: undefined; height: number }
    | { width: number; height: number }
);

export interface BestFitImageSize {
    type: ImageSizeType.BEST_FIT;
    width: number;
    height: number;
}

export interface ImageRotation {
    degrees: number;
    mirrored: boolean;
}

export enum ImageQuality {
    COLOR = "color",
    GRAY = "gray",
    BITONAL = "bitonal",
    DEFAULT = "default",
}

export function parseRequest(
    pathSegments: string[]
): ImageInfoRequest | ImageRequest | null {
    // don't allow empty identifiers
    if (!pathSegments[0]) return null;
    if (
        pathSegments.length === 1 ||
        (pathSegments.length === 2 &&
            (pathSegments[1] === "" || pathSegments[1] === "info.json"))
    ) {
        return {
            type: ImageRequestType.IMAGE_INFO,
            identifier: pathSegments[0],
            name: pathSegments[1] as ImageInfoRequest["name"],
        };
    } else if (pathSegments.length !== 5) return null;
    const [identifier, rawRegion, rawSize, rawRotation, rawName] = pathSegments;
    const region = parseRegion(rawRegion);
    const size = parseSize(rawSize);
    const rotation = parseRotation(rawRotation);
    const name = parseName(rawName);
    if (!(region && size && rotation && name)) return null;
    return {
        type: ImageRequestType.IMAGE,
        identifier,
        region,
        size,
        rotation,
        ...name,
    };
}
export function formatRequest(req: ImageInfoRequest | ImageRequest): string[] {
    return req.type === ImageRequestType.IMAGE
        ? formatImageRequest(req)
        : formatImageInfoRequest(req);
}

export function formatImageInfoRequest(req: ImageInfoRequest): string[] {
    return req.name === undefined
        ? [req.identifier]
        : [req.identifier, req.name];
}

export function formatImageRequest(req: ImageRequest): string[] {
    return [
        req.identifier,
        formatRegion(req.region),
        formatSize(req.size),
        formatRotation(req.rotation),
        formatName(req),
    ];
}

const REGION = new RegExp(
    `` +
        `^(?:` +
        // named regions are handled separately
        // Relative percentage coords (can be real numbers)
        `(pct:)(\\d{1,10}(?:,\\d{0,10})?),` +
        `(\\d{1,10}(?:,\\d{0,10})?),` +
        `(\\d{1,10}(?:,\\d{0,10})?),` +
        `(\\d{1,10}(?:,\\d{0,10})?)` +
        `|` +
        // Regular pixel coords (only integers)
        `(?:(\\d{1,10}),(\\d{1,10}),(\\d{1,10}),(\\d{1,10}))` +
        `)$`
);

export function parseRegion(region: string): ImageRegion | null {
    if (region === "full") return REGION_FULL;
    else if (region === "square") return REGION_SQUARE;
    const match = REGION.exec(region);
    if (!match) return null;
    const type = match[1] ? ImageRegionType.RELATIVE : ImageRegionType.ABSOLUTE;
    const [x, y, width, height] = match
        .slice(type === ImageRegionType.RELATIVE ? 2 : 6)
        .map(Number.parseFloat);
    return {
        type,
        x,
        y,
        width,
        height,
    };
}

export function formatRegion(region: ImageRegion): string {
    if (region.type === ImageRegionType.NAMED) return region.name;
    return `${region.type === ImageRegionType.RELATIVE ? "pct:" : ""}${[
        region.x,
        region.y,
        region.width,
        region.height,
    ]
        .map(formatNormalisedNumber)
        .join(",")}`;
}

export function formatNormalisedNumber(n: number): string {
    const fixed = n.toFixed(10);
    return fixed.includes(".") ? fixed.replace(/\.?0*$/, "") : fixed;
}

const SIZE =
    /^(?:(?:pct:(\d{1,10}(?:\.\d{0,10})?))|(!?)(\d{1,10})?,(\d{1,10})?)$/;

export function parseSize(size: string): ImageSize | null {
    if (size === "full" || size === "max") {
        return { type: ImageSizeType.NAMED, name: size };
    }
    const match = SIZE.exec(size);
    if (match?.[1]) {
        return {
            type: ImageSizeType.RELATIVE,
            proportion: Number.parseFloat(match[1]),
        };
    }
    const width = (match?.[3] && Number.parseInt(match[3], 10)) || undefined;
    const height = (match?.[4] && Number.parseInt(match[4], 10)) || undefined;
    if (match?.[2] && match?.[3] && match?.[4]) {
        return { type: ImageSizeType.BEST_FIT, width: width!, height: height! };
    }
    if (!match?.[2]) {
        return { type: ImageSizeType.ABSOLUTE, width: width!, height: height! };
    }
    return null;
}

export function formatSize(size: ImageSize): string {
    if (size.type === ImageSizeType.NAMED) return size.name;
    if (size.type === ImageSizeType.RELATIVE) {
        return `pct:${formatNormalisedNumber(size.proportion)}`;
    }
    return `${size.type === ImageSizeType.BEST_FIT ? "!" : ""}${
        size.width === undefined ? "" : size.width
    },${size.height === undefined ? "" : size.height}`;
}

const ROTATION = /^(!)?(-?\d{1,10}(?:\.\d{0,10})?)$/;

export function parseRotation(rotation: string): ImageRotation | null {
    const match = ROTATION.exec(rotation);
    if (!match) return null;
    return { mirrored: !!match[1], degrees: Number.parseFloat(match[2]) };
}

export function formatRotation(rotation: ImageRotation): string {
    return `${rotation.mirrored ? "!" : ""}${formatNormalisedNumber(
        rotation.degrees
    )}`;
}

const qualities = new Set(Object.values(ImageQuality));

export function parseQuality(quality: string): ImageQuality | null {
    return qualities.has(quality as ImageQuality)
        ? (quality as ImageQuality)
        : null;
}

export function formatQuality(quality: ImageQuality): string {
    return quality as string;
}

const FORMAT = /^([a-zA-Z0-9]+)$/;

export function parseFormat(format: string): string | null {
    return FORMAT.test(format) ? format : null;
}

export function parseName(
    name: string
): { quality: ImageQuality; format: string } | null {
    const [rawQuality, rawFormat, ...rest] = name.split(".") as Array<
        string | undefined
    >;
    const quality = parseQuality(rawQuality || "");
    const format = parseFormat(rawFormat || "");
    if (quality === null || format === null || rest.length) return null;
    return { quality, format };
}

export function formatName(qualityFormat: {
    quality: ImageQuality;
    format: string;
}): string {
    return `${qualityFormat.quality}.${qualityFormat.format}`;
}

/**
 * Perform as much [canonicalisation] as is possible without knowing the
 * dimensions of an image.
 *
 * [canonicalisation]: https://iiif.io/api/image/2.1/#canonical-uri-syntax
 *
 * @returns The req unchanged if it's already canonical, otherwise a new req
 *   identifying the same image region, but in canonical form.
 */
export function canonicaliseRequestWithoutDimensions<
    T extends ImageRequest | ImageInfoRequest
>(req: T): T {
    if (req.type === ImageRequestType.IMAGE) {
        return _canonicaliseImageRequestWithoutDimensions(req) as T;
    }
    return req.name === "info.json" ? req : { ...req, name: "info.json" };
}

function _canonicaliseImageRequestWithoutDimensions(
    req: ImageRequest
): ImageRequest {
    // Only size and rotation can be canonicalised without image dimensions
    const canonicalisedSize = _canonicaliseSizeWithoutDimentions(req);
    const canonicalisedRotation = _canonicaliseRotation(req.rotation);
    if (canonicalisedSize === null && canonicalisedRotation === null)
        return req;
    return {
        ...req,
        size: canonicalisedSize || req.size,
        rotation: canonicalisedRotation || req.rotation,
    };
}

function _canonicaliseSizeWithoutDimentions(
    req: ImageRequest
): AbsoluteImageSize | null {
    if (
        !(
            req.size.type === ImageSizeType.ABSOLUTE &&
            req.region.type === ImageRegionType.ABSOLUTE
        )
    )
        return null;
    let { width, height } = req.size;

    if (height === undefined) return null; // already canonical
    else if (width === undefined) {
        const heightRatio = height / req.region.height;
        width = Math.round(req.region.width * heightRatio);
        return { type: ImageSizeType.ABSOLUTE, width, height: undefined };
    }
    // Eliminate the height if it is within the range that could have resulted
    // from scaling and rounding the region uniformly to our width.
    const maxWidthScale = (width + 0.5) / req.region.width;
    const minWidthScale = (width - 0.5) / req.region.width;
    const maxHeight = req.region.height * maxWidthScale;
    const minHeight = req.region.height * minWidthScale;

    if (minHeight <= height && height <= maxHeight) {
        return { type: ImageSizeType.ABSOLUTE, width, height: undefined };
    }
    return null;
}

function _canonicaliseRotation(rotation: ImageRotation): ImageRotation | null {
    // Add 360 because the result the first mod is -360 < n < 360 but we want
    // 0 <= n < 360.
    const canonicalDegrees = ((rotation.degrees % 360) + 360) % 360;
    return canonicalDegrees === rotation.degrees
        ? null
        : { mirrored: rotation.mirrored, degrees: canonicalDegrees };
}
