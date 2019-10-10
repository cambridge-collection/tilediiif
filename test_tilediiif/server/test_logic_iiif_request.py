from decimal import Decimal

import pytest

from tilediiif.server.logic import (
    AbsoluteIIIFRegion, BestFitIIIFSize, IIIFImageRequest, IIIFRotation,
    IIIFSize, NamedIIIFRegion, NamedIIIFSize, RelativeIIIFRegion,
    RelativeIIIFSize)


@pytest.mark.parametrize('region, expected', [
    ['full', NamedIIIFRegion.FULL],
    ['square', NamedIIIFRegion.SQUARE],
    ['10,11,12,13', AbsoluteIIIFRegion(x=10, y=11, width=12, height=13)],
    ['pct:10,11,12,13',
     RelativeIIIFRegion(x=Decimal(10), y=Decimal(11),
                        width=Decimal(12), height=Decimal(13))],
    ['pct:10.1,11.2,12.3,13.4',
     RelativeIIIFRegion(x=Decimal('10.1'), y=Decimal('11.2'),
                        width=Decimal('12.3'), height=Decimal('13.4'))],
])
def test_parse_region_roundtrip(region, expected):
    parsed = IIIFImageRequest.parse_region(region)
    assert parsed == expected
    assert str(parsed) == region


@pytest.mark.parametrize('size, expected', [
    ['full', NamedIIIFSize.FULL],
    ['max', NamedIIIFSize.MAX],
    ['23,', IIIFSize(23, None)],
    [',23', IIIFSize(None, 23)],
    ['23,32', IIIFSize(23, 32)],
    ['!23,32', BestFitIIIFSize(23, 32)],
    ['pct:23', RelativeIIIFSize(Decimal(23))],
    ['pct:23.32', RelativeIIIFSize(Decimal('23.32'))],
])
def test_parse_size_roundtrip(size, expected):
    parsed = IIIFImageRequest.parse_size(size)
    assert parsed == expected
    assert str(parsed) == size


@pytest.mark.parametrize('rotation, expected', [
    ['0', IIIFRotation(False, Decimal(0))],
    ['90', IIIFRotation(False, Decimal(90))],
    ['90.99', IIIFRotation(False, Decimal('90.99'))],
    ['!0', IIIFRotation(True, Decimal(0))],
    ['!90', IIIFRotation(True, Decimal(90))],
    ['!90.99', IIIFRotation(True, Decimal('90.99'))],
])
def test_parse_rotation_roundtrip(rotation, expected):
    parsed = IIIFImageRequest.parse_rotation(rotation)
    assert parsed == expected
    assert str(parsed) == rotation


@pytest.mark.parametrize('quality, expected', [
    ['default', 'default'],
    ['foo', 'foo']
])
def test_parse_quality_roundtrip(quality, expected):
    parsed = IIIFImageRequest.parse_quality(quality)
    assert parsed == expected
    assert str(parsed) == quality


@pytest.mark.parametrize('format, expected', [
    ['jpg', 'jpg'],
    ['foo', 'foo']
])
def test_parse_format_roundtrip(format, expected):
    parsed = IIIFImageRequest.parse_quality(format)
    assert parsed == expected
    assert str(parsed) == format


@pytest.mark.parametrize('request_path, expected', [
    ['full/full/0/default.png', IIIFImageRequest(
        NamedIIIFRegion.FULL,
        NamedIIIFSize.FULL,
        IIIFRotation(mirrored=False, degrees=Decimal(0)),
        'default', 'png'
    )],
    ['1,2,3,4/5,6/7.5/foo.bar', IIIFImageRequest(
        region=AbsoluteIIIFRegion(1, 2, 3, 4),
        size=IIIFSize(5, 6),
        rotation=IIIFRotation(mirrored=False, degrees=Decimal('7.5')),
        quality='foo', format='bar'
    )],
])
def test_parse_iiif_image_request_roundtrip(request_path, expected):
    parsed = IIIFImageRequest.parse_request(request_path)
    assert parsed == expected
    assert str(parsed) == request_path


def test_parse_iiif_image_request_parts():
    parsed = IIIFImageRequest.parse(
        region='0,0,10,10', size='5,5', rotation='0', quality='default',
        format='jpg')
    expected = '0,0,10,10/5,5/0/default.jpg'
    assert str(parsed) == expected
    assert IIIFImageRequest.parse_request(expected) == parsed


@pytest.mark.parametrize('request_path, expected', [
    ['full/full/0/default.jpg', None],
    ['pct:0,0,100,100/full/0/default.jpg', None],
    ['pct:0,0,100,100/50,50/0/default.jpg', None],
    ['0,0,100,100/50,/0/default.jpg', None],
    ['0,0,100,100/,50/0/default.jpg', None],
    ['0,0,100,100/50,50/0/default.jpg', '0,0,100,100/50,/0/default.jpg'],
    ['full/full/360/default.jpg', 'full/full/0/default.jpg'],
    ['full/full/!360/default.jpg', 'full/full/!0/default.jpg'],
    ['full/full/365.3/default.jpg', 'full/full/5.3/default.jpg'],
    ['full/full/!365.3/default.jpg', 'full/full/!5.3/default.jpg'],
])
def test_image_request_canonicalisation(request_path, expected):
    initial = IIIFImageRequest.parse_request(request_path)
    canonical = initial.canonical()

    if expected is None:
        assert initial is canonical
        assert str(canonical) == request_path
    else:
        assert initial is not canonical
        assert str(canonical) == expected


def test_image_request_string_representation_normalises_real_numbers():
    request_path = 'pct:0.,0.0,50.500,01.010/pct:0050.10/00.00/default.jpg'
    normalised_path = 'pct:0,0,50.5,1.01/pct:50.1/0/default.jpg'
    assert str(IIIFImageRequest.parse_request(request_path)) == normalised_path


@pytest.mark.parametrize('request_path, msg', [
    ['/full/full/0/default.jpg', 'invalid request: '],
    ['foo/full/0/default.jpg', 'invalid region: foo'],
    ['full/foo/0/default.jpg', 'invalid size: foo'],
    ['full/full/foo/default.jpg', 'invalid rotation: foo'],
    ['full/full/0/dEfaUlt.jpg', 'invalid quality: dEfaUlt'],
    ['full/full/0/default.jPg', 'invalid format: jPg'],
])
def test_parsing_invalid_image_request_raises_error(request_path, msg):
    with pytest.raises(ValueError) as exc_info:
        IIIFImageRequest.parse_request(request_path)
    assert msg in str(exc_info.value)
