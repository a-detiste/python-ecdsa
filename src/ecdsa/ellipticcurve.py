#! /usr/bin/env python
# -*- coding: utf-8 -*-
#
# Implementation of elliptic curves, for cryptographic applications.
#
# This module doesn't provide any way to choose a random elliptic
# curve, nor to verify that an elliptic curve was chosen randomly,
# because one can simply use NIST's standard curves.
#
# Notes from X9.62-1998 (draft):
#   Nomenclature:
#     - Q is a public key.
#     The "Elliptic Curve Domain Parameters" include:
#     - q is the "field size", which in our case equals p.
#     - p is a big prime.
#     - G is a point of prime order (5.1.1.1).
#     - n is the order of G (5.1.1.1).
#   Public-key validation (5.2.2):
#     - Verify that Q is not the point at infinity.
#     - Verify that X_Q and Y_Q are in [0,p-1].
#     - Verify that Q is on the curve.
#     - Verify that nQ is the point at infinity.
#   Signature generation (5.3):
#     - Pick random k from [1,n-1].
#   Signature checking (5.4.2):
#     - Verify that r and s are in [1,n-1].
#
# Revision history:
#    2005.12.31 - Initial version.
#    2008.11.25 - Change CurveFp.is_on to contains_point.
#
# Written in 2005 by Peter Pearson and placed in the public domain.
# Modified extensively as part of python-ecdsa.

from __future__ import division

try:
    from gmpy2 import mpz

    GMPY = True
except ImportError:  # pragma: no branch
    try:
        from gmpy import mpz

        GMPY = True
    except ImportError:
        GMPY = False


from six import python_2_unicode_compatible
from . import numbertheory
from ._compat import normalise_bytes
from .errors import MalformedPointError
from .util import orderlen, string_to_number, number_to_string


@python_2_unicode_compatible
class CurveFp(object):
    """Short Weierstrass Elliptic Curve over a prime field."""

    if GMPY:  # pragma: no branch

        def __init__(self, p, a, b, h=None):
            """
            The curve of points satisfying y^2 = x^3 + a*x + b (mod p).

            h is an integer that is the cofactor of the elliptic curve domain
            parameters; it is the number of points satisfying the elliptic
            curve equation divided by the order of the base point. It is used
            for selection of efficient algorithm for public point verification.
            """
            self.__p = mpz(p)
            self.__a = mpz(a)
            self.__b = mpz(b)
            # h is not used in calculations and it can be None, so don't use
            # gmpy with it
            self.__h = h

    else:  # pragma: no branch

        def __init__(self, p, a, b, h=None):
            """
            The curve of points satisfying y^2 = x^3 + a*x + b (mod p).

            h is an integer that is the cofactor of the elliptic curve domain
            parameters; it is the number of points satisfying the elliptic
            curve equation divided by the order of the base point. It is used
            for selection of efficient algorithm for public point verification.
            """
            self.__p = p
            self.__a = a
            self.__b = b
            self.__h = h

    def __eq__(self, other):
        """Return True if other is an identical curve, False otherwise.

        Note: the value of the cofactor of the curve is not taken into account
        when comparing curves, as it's derived from the base point and
        intrinsic curve characteristic (but it's complex to compute),
        only the prime and curve parameters are considered.
        """
        if isinstance(other, CurveFp):
            p = self.__p
            return (
                self.__p == other.__p
                and self.__a % p == other.__a % p
                and self.__b % p == other.__b % p
            )
        return NotImplemented

    def __ne__(self, other):
        """Return False if other is an identical curve, True otherwise."""
        return not self == other

    def __hash__(self):
        return hash((self.__p, self.__a, self.__b))

    def p(self):
        return self.__p

    def a(self):
        return self.__a

    def b(self):
        return self.__b

    def cofactor(self):
        return self.__h

    def contains_point(self, x, y):
        """Is the point (x,y) on this curve?"""
        return (y * y - ((x * x + self.__a) * x + self.__b)) % self.__p == 0

    def __str__(self):
        return "CurveFp(p=%d, a=%d, b=%d, h=%d)" % (
            self.__p,
            self.__a,
            self.__b,
            self.__h,
        )


class CurveEdTw(object):
    """Parameters for a Twisted Edwards Elliptic Curve"""

    if GMPY:  # pragma: no branch

        def __init__(self, p, a, d, h=None):
            """
            The curve of points satisfying a*x^2 + y^2 = 1 + d*x^2*y^2 (mod p).

            h is the cofactor of the curve.
            """
            self.__p = mpz(p)
            self.__a = mpz(a)
            self.__d = mpz(d)
            self.__h = h

    else:

        def __init__(self, p, a, d, h=None):
            """
            The curve of points satisfying a*x^2 + y^2 = 1 + d*x^2*y^2 (mod p).

            h is the cofactor of the curve.
            """
            self.__p = p
            self.__a = a
            self.__d = d
            self.__h = h

    def __eq__(self, other):
        """Returns True if other is an identical curve."""
        if isinstance(other, CurveEdTw):
            p = self.__p
            return (
                self.__p == other.__p
                and self.__a % p == other.__a % p
                and self.__d % p == other.__d % p
            )
        return NotImplemented

    def __ne__(self, other):
        """Return False if the other is an identical curve, True otherwise."""
        return not self == other

    def __hash__(self):
        return hash((self.__p, self.__a, self.__d))

    def contains_point(self, x, y):
        """Is the point (x, y) on this curve?"""
        return (
            self.__a * x * x + y * y - 1 - self.__d * x * x * y * y
        ) % self.__p == 0

    def p(self):
        return self.__p

    def a(self):
        return self.__a

    def d(self):
        return self.__d

    def cofactor(self):
        return self.__h

    def __str__(self):
        return "CurveEdTw(p={0}, a={1}, d={2}, h={3})".format(
            self.__p, self.__a, self.__d, self.__h,
        )


class AbstractPoint(object):
    """Class for common methods of elliptic curve points."""

    @staticmethod
    def _from_raw_encoding(data, raw_encoding_length):
        """
        Decode public point from :term:`raw encoding`.

        :term:`raw encoding` is the same as the :term:`uncompressed` encoding,
        but without the 0x04 byte at the beginning.
        """
        # real assert, from_bytes() should not call us with different length
        assert len(data) == raw_encoding_length
        xs = data[: raw_encoding_length // 2]
        ys = data[raw_encoding_length // 2 :]
        # real assert, raw_encoding_length is calculated by multiplying an
        # integer by two so it will always be even
        assert len(xs) == raw_encoding_length // 2
        assert len(ys) == raw_encoding_length // 2
        coord_x = string_to_number(xs)
        coord_y = string_to_number(ys)

        return coord_x, coord_y

    @staticmethod
    def _from_compressed(data, curve):
        """Decode public point from compressed encoding."""
        if data[:1] not in (b"\x02", b"\x03"):
            raise MalformedPointError("Malformed compressed point encoding")

        is_even = data[:1] == b"\x02"
        x = string_to_number(data[1:])
        p = curve.p()
        alpha = (pow(x, 3, p) + (curve.a() * x) + curve.b()) % p
        try:
            beta = numbertheory.square_root_mod_prime(alpha, p)
        except numbertheory.SquareRootError as e:
            raise MalformedPointError(
                "Encoding does not correspond to a point on curve", e
            )
        if is_even == bool(beta & 1):
            y = p - beta
        else:
            y = beta
        return x, y

    @classmethod
    def _from_hybrid(cls, data, raw_encoding_length, validate_encoding):
        """Decode public point from hybrid encoding."""
        # real assert, from_bytes() should not call us with different types
        assert data[:1] in (b"\x06", b"\x07")

        # primarily use the uncompressed as it's easiest to handle
        x, y = cls._from_raw_encoding(data[1:], raw_encoding_length)

        # but validate if it's self-consistent if we're asked to do that
        if validate_encoding and (
            y & 1
            and data[:1] != b"\x07"
            or (not y & 1)
            and data[:1] != b"\x06"
        ):
            raise MalformedPointError("Inconsistent hybrid point encoding")

        return x, y

    @classmethod
    def from_bytes(
        cls, curve, data, validate_encoding=True, valid_encodings=None
    ):
        """
        Initialise the object from byte encoding of a point.

        The method does accept and automatically detect the type of point
        encoding used. It supports the :term:`raw encoding`,
        :term:`uncompressed`, :term:`compressed`, and :term:`hybrid` encodings.

        Note: generally you will want to call the ``from_bytes()`` method of
        either a child class, PointJacobi or Point.

        :param data: single point encoding of the public key
        :type data: :term:`bytes-like object`
        :param curve: the curve on which the public key is expected to lay
        :type curve: ecdsa.ellipticcurve.CurveFp
        :param validate_encoding: whether to verify that the encoding of the
            point is self-consistent, defaults to True, has effect only
            on ``hybrid`` encoding
        :type validate_encoding: bool
        :param valid_encodings: list of acceptable point encoding formats,
            supported ones are: :term:`uncompressed`, :term:`compressed`,
            :term:`hybrid`, and :term:`raw encoding` (specified with ``raw``
            name). All formats by default (specified with ``None``).
        :type valid_encodings: :term:`set-like object`

        :raises MalformedPointError: if the public point does not lay on the
            curve or the encoding is invalid

        :return: x and y coordinates of the encoded point
        :rtype: tuple(int, int)
        """
        if not valid_encodings:
            valid_encodings = set(
                ["uncompressed", "compressed", "hybrid", "raw"]
            )
        if not all(
            i in set(("uncompressed", "compressed", "hybrid", "raw"))
            for i in valid_encodings
        ):
            raise ValueError(
                "Only uncompressed, compressed, hybrid or raw encoding "
                "supported."
            )
        data = normalise_bytes(data)
        key_len = len(data)
        raw_encoding_length = 2 * orderlen(curve.p())
        if key_len == raw_encoding_length and "raw" in valid_encodings:
            coord_x, coord_y = cls._from_raw_encoding(
                data, raw_encoding_length
            )
        elif key_len == raw_encoding_length + 1 and (
            "hybrid" in valid_encodings or "uncompressed" in valid_encodings
        ):
            if data[:1] in (b"\x06", b"\x07") and "hybrid" in valid_encodings:
                coord_x, coord_y = cls._from_hybrid(
                    data, raw_encoding_length, validate_encoding
                )
            elif data[:1] == b"\x04" and "uncompressed" in valid_encodings:
                coord_x, coord_y = cls._from_raw_encoding(
                    data[1:], raw_encoding_length
                )
            else:
                raise MalformedPointError(
                    "Invalid X9.62 encoding of the public point"
                )
        elif (
            key_len == raw_encoding_length // 2 + 1
            and "compressed" in valid_encodings
        ):
            coord_x, coord_y = cls._from_compressed(data, curve)
        else:
            raise MalformedPointError(
                "Length of string does not match lengths of "
                "any of the enabled ({0}) encodings of the "
                "curve.".format(", ".join(valid_encodings))
            )
        return coord_x, coord_y

    def _raw_encode(self):
        """Convert the point to the :term:`raw encoding`."""
        prime = self.curve().p()
        x_str = number_to_string(self.x(), prime)
        y_str = number_to_string(self.y(), prime)
        return x_str + y_str

    def _compressed_encode(self):
        """Encode the point into the compressed form."""
        prime = self.curve().p()
        x_str = number_to_string(self.x(), prime)
        if self.y() & 1:
            return b"\x03" + x_str
        return b"\x02" + x_str

    def _hybrid_encode(self):
        """Encode the point into the hybrid form."""
        raw_enc = self._raw_encode()
        if self.y() & 1:
            return b"\x07" + raw_enc
        return b"\x06" + raw_enc

    def to_bytes(self, encoding="raw"):
        """
        Convert the point to a byte string.

        The method by default uses the :term:`raw encoding` (specified
        by `encoding="raw"`. It can also output points in :term:`uncompressed`,
        :term:`compressed`, and :term:`hybrid` formats.

        :return: :term:`raw encoding` of a public on the curve
        :rtype: bytes
        """
        assert encoding in ("raw", "uncompressed", "compressed", "hybrid")
        if encoding == "raw":
            return self._raw_encode()
        elif encoding == "uncompressed":
            return b"\x04" + self._raw_encode()
        elif encoding == "hybrid":
            return self._hybrid_encode()
        else:
            return self._compressed_encode()

    @staticmethod
    def _naf(mult):
        """Calculate non-adjacent form of number."""
        ret = []
        while mult:
            if mult % 2:
                nd = mult % 4
                if nd >= 2:
                    nd -= 4
                ret.append(nd)
                mult -= nd
            else:
                ret.append(0)
            mult //= 2
        return ret


class PointJacobi(AbstractPoint):
    """
    Point on a short Weierstrass elliptic curve. Uses Jacobi coordinates.

    In Jacobian coordinates, there are three parameters, X, Y and Z.
    They correspond to affine parameters 'x' and 'y' like so:

    x = X / Z²
    y = Y / Z³
    """

    def __init__(self, curve, x, y, z, order=None, generator=False):
        """
        Initialise a point that uses Jacobi representation internally.

        :param CurveFp curve: curve on which the point resides
        :param int x: the X parameter of Jacobi representation (equal to x when
          converting from affine coordinates
        :param int y: the Y parameter of Jacobi representation (equal to y when
          converting from affine coordinates
        :param int z: the Z parameter of Jacobi representation (equal to 1 when
          converting from affine coordinates
        :param int order: the point order, must be non zero when using
          generator=True
        :param bool generator: the point provided is a curve generator, as
          such, it will be commonly used with scalar multiplication. This will
          cause to precompute multiplication table generation for it
        """
        super(PointJacobi, self).__init__()
        self.__curve = curve
        if GMPY:  # pragma: no branch
            self.__coords = (mpz(x), mpz(y), mpz(z))
            self.__order = order and mpz(order)
        else:  # pragma: no branch
            self.__coords = (x, y, z)
            self.__order = order
        self.__generator = generator
        self.__precompute = []

    @classmethod
    def from_bytes(
        cls,
        curve,
        data,
        validate_encoding=True,
        valid_encodings=None,
        order=None,
        generator=False,
    ):
        """
        Initialise the object from byte encoding of a point.

        The method does accept and automatically detect the type of point
        encoding used. It supports the :term:`raw encoding`,
        :term:`uncompressed`, :term:`compressed`, and :term:`hybrid` encodings.

        :param data: single point encoding of the public key
        :type data: :term:`bytes-like object`
        :param curve: the curve on which the public key is expected to lay
        :type curve: ecdsa.ellipticcurve.CurveFp
        :param validate_encoding: whether to verify that the encoding of the
            point is self-consistent, defaults to True, has effect only
            on ``hybrid`` encoding
        :type validate_encoding: bool
        :param valid_encodings: list of acceptable point encoding formats,
            supported ones are: :term:`uncompressed`, :term:`compressed`,
            :term:`hybrid`, and :term:`raw encoding` (specified with ``raw``
            name). All formats by default (specified with ``None``).
        :type valid_encodings: :term:`set-like object`
        :param int order: the point order, must be non zero when using
            generator=True
        :param bool generator: the point provided is a curve generator, as
            such, it will be commonly used with scalar multiplication. This
            will cause to precompute multiplication table generation for it

        :raises MalformedPointError: if the public point does not lay on the
            curve or the encoding is invalid

        :return: Point on curve
        :rtype: PointJacobi
        """
        coord_x, coord_y = super(PointJacobi, cls).from_bytes(
            curve, data, validate_encoding, valid_encodings
        )
        return PointJacobi(curve, coord_x, coord_y, 1, order, generator)

    def _maybe_precompute(self):
        if not self.__generator or self.__precompute:
            return

        # since this code will execute just once, and it's fully deterministic,
        # depend on atomicity of the last assignment to switch from empty
        # self.__precompute to filled one and just ignore the unlikely
        # situation when two threads execute it at the same time (as it won't
        # lead to inconsistent __precompute)
        order = self.__order
        assert order
        precompute = []
        i = 1
        order *= 2
        coord_x, coord_y, coord_z = self.__coords
        doubler = PointJacobi(self.__curve, coord_x, coord_y, coord_z, order)
        order *= 2
        precompute.append((doubler.x(), doubler.y()))

        while i < order:
            i *= 2
            doubler = doubler.double().scale()
            precompute.append((doubler.x(), doubler.y()))

        self.__precompute = precompute

    def __getstate__(self):
        # while this code can execute at the same time as _maybe_precompute()
        # is updating the __precompute or scale() is updating the __coords,
        # there is no requirement for consistency between __coords and
        # __precompute
        state = self.__dict__.copy()
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)

    def __eq__(self, other):
        """Compare for equality two points with each-other.

        Note: only points that lay on the same curve can be equal.
        """
        x1, y1, z1 = self.__coords
        if other is INFINITY:
            return not y1 or not z1
        if isinstance(other, Point):
            x2, y2, z2 = other.x(), other.y(), 1
        elif isinstance(other, PointJacobi):
            x2, y2, z2 = other.__coords
        else:
            return NotImplemented
        if self.__curve != other.curve():
            return False
        p = self.__curve.p()

        zz1 = z1 * z1 % p
        zz2 = z2 * z2 % p

        # compare the fractions by bringing them to the same denominator
        # depend on short-circuit to save 4 multiplications in case of
        # inequality
        return (x1 * zz2 - x2 * zz1) % p == 0 and (
            y1 * zz2 * z2 - y2 * zz1 * z1
        ) % p == 0

    def __ne__(self, other):
        """Compare for inequality two points with each-other."""
        return not self == other

    def order(self):
        """Return the order of the point.

        None if it is undefined.
        """
        return self.__order

    def curve(self):
        """Return curve over which the point is defined."""
        return self.__curve

    def x(self):
        """
        Return affine x coordinate.

        This method should be used only when the 'y' coordinate is not needed.
        It's computationally more efficient to use `to_affine()` and then
        call x() and y() on the returned instance. Or call `scale()`
        and then x() and y() on the returned instance.
        """
        x, _, z = self.__coords
        if z == 1:
            return x
        p = self.__curve.p()
        z = numbertheory.inverse_mod(z, p)
        return x * z ** 2 % p

    def y(self):
        """
        Return affine y coordinate.

        This method should be used only when the 'x' coordinate is not needed.
        It's computationally more efficient to use `to_affine()` and then
        call x() and y() on the returned instance. Or call `scale()`
        and then x() and y() on the returned instance.
        """
        _, y, z = self.__coords
        if z == 1:
            return y
        p = self.__curve.p()
        z = numbertheory.inverse_mod(z, p)
        return y * z ** 3 % p

    def scale(self):
        """
        Return point scaled so that z == 1.

        Modifies point in place, returns self.
        """
        x, y, z = self.__coords
        if z == 1:
            return self

        # scaling is deterministic, so even if two threads execute the below
        # code at the same time, they will set __coords to the same value
        p = self.__curve.p()
        z_inv = numbertheory.inverse_mod(z, p)
        zz_inv = z_inv * z_inv % p
        x = x * zz_inv % p
        y = y * zz_inv * z_inv % p
        self.__coords = (x, y, 1)
        return self

    def to_affine(self):
        """Return point in affine form."""
        _, y, z = self.__coords
        if not y or not z:
            return INFINITY
        self.scale()
        x, y, z = self.__coords
        return Point(self.__curve, x, y, self.__order)

    @staticmethod
    def from_affine(point, generator=False):
        """Create from an affine point.

        :param bool generator: set to True to make the point to precalculate
          multiplication table - useful for public point when verifying many
          signatures (around 100 or so) or for generator points of a curve.
        """
        return PointJacobi(
            point.curve(), point.x(), point.y(), 1, point.order(), generator
        )

    # please note that all the methods that use the equations from
    # hyperelliptic
    # are formatted in a way to maximise performance.
    # Things that make code faster: multiplying instead of taking to the power
    # (`xx = x * x; xxxx = xx * xx % p` is faster than `xxxx = x**4 % p` and
    # `pow(x, 4, p)`),
    # multiple assignments at the same time (`x1, x2 = self.x1, self.x2` is
    # faster than `x1 = self.x1; x2 = self.x2`),
    # similarly, sometimes the `% p` is skipped if it makes the calculation
    # faster and the result of calculation is later reduced modulo `p`

    def _double_with_z_1(self, X1, Y1, p, a):
        """Add a point to itself with z == 1."""
        # after:
        # http://hyperelliptic.org/EFD/g1p/auto-shortw-jacobian.html#doubling-mdbl-2007-bl
        XX, YY = X1 * X1 % p, Y1 * Y1 % p
        if not YY:
            return 0, 0, 1
        YYYY = YY * YY % p
        S = 2 * ((X1 + YY) ** 2 - XX - YYYY) % p
        M = 3 * XX + a
        T = (M * M - 2 * S) % p
        # X3 = T
        Y3 = (M * (S - T) - 8 * YYYY) % p
        Z3 = 2 * Y1 % p
        return T, Y3, Z3

    def _double(self, X1, Y1, Z1, p, a):
        """Add a point to itself, arbitrary z."""
        if Z1 == 1:
            return self._double_with_z_1(X1, Y1, p, a)
        if not Y1 or not Z1:
            return 0, 0, 1
        # after:
        # http://hyperelliptic.org/EFD/g1p/auto-shortw-jacobian.html#doubling-dbl-2007-bl
        XX, YY = X1 * X1 % p, Y1 * Y1 % p
        if not YY:
            return 0, 0, 1
        YYYY = YY * YY % p
        ZZ = Z1 * Z1 % p
        S = 2 * ((X1 + YY) ** 2 - XX - YYYY) % p
        M = (3 * XX + a * ZZ * ZZ) % p
        T = (M * M - 2 * S) % p
        # X3 = T
        Y3 = (M * (S - T) - 8 * YYYY) % p
        Z3 = ((Y1 + Z1) ** 2 - YY - ZZ) % p

        return T, Y3, Z3

    def double(self):
        """Add a point to itself."""
        X1, Y1, Z1 = self.__coords

        if not Y1:
            return INFINITY

        p, a = self.__curve.p(), self.__curve.a()

        X3, Y3, Z3 = self._double(X1, Y1, Z1, p, a)

        if not Y3 or not Z3:
            return INFINITY
        return PointJacobi(self.__curve, X3, Y3, Z3, self.__order)

    def _add_with_z_1(self, X1, Y1, X2, Y2, p):
        """add points when both Z1 and Z2 equal 1"""
        # after:
        # http://hyperelliptic.org/EFD/g1p/auto-shortw-jacobian.html#addition-mmadd-2007-bl
        H = X2 - X1
        HH = H * H
        I = 4 * HH % p
        J = H * I
        r = 2 * (Y2 - Y1)
        if not H and not r:
            return self._double_with_z_1(X1, Y1, p, self.__curve.a())
        V = X1 * I
        X3 = (r ** 2 - J - 2 * V) % p
        Y3 = (r * (V - X3) - 2 * Y1 * J) % p
        Z3 = 2 * H % p
        return X3, Y3, Z3

    def _add_with_z_eq(self, X1, Y1, Z1, X2, Y2, p):
        """add points when Z1 == Z2"""
        # after:
        # http://hyperelliptic.org/EFD/g1p/auto-shortw-jacobian.html#addition-zadd-2007-m
        A = (X2 - X1) ** 2 % p
        B = X1 * A % p
        C = X2 * A
        D = (Y2 - Y1) ** 2 % p
        if not A and not D:
            return self._double(X1, Y1, Z1, p, self.__curve.a())
        X3 = (D - B - C) % p
        Y3 = ((Y2 - Y1) * (B - X3) - Y1 * (C - B)) % p
        Z3 = Z1 * (X2 - X1) % p
        return X3, Y3, Z3

    def _add_with_z2_1(self, X1, Y1, Z1, X2, Y2, p):
        """add points when Z2 == 1"""
        # after:
        # http://hyperelliptic.org/EFD/g1p/auto-shortw-jacobian.html#addition-madd-2007-bl
        Z1Z1 = Z1 * Z1 % p
        U2, S2 = X2 * Z1Z1 % p, Y2 * Z1 * Z1Z1 % p
        H = (U2 - X1) % p
        HH = H * H % p
        I = 4 * HH % p
        J = H * I
        r = 2 * (S2 - Y1) % p
        if not r and not H:
            return self._double_with_z_1(X2, Y2, p, self.__curve.a())
        V = X1 * I
        X3 = (r * r - J - 2 * V) % p
        Y3 = (r * (V - X3) - 2 * Y1 * J) % p
        Z3 = ((Z1 + H) ** 2 - Z1Z1 - HH) % p
        return X3, Y3, Z3

    def _add_with_z_ne(self, X1, Y1, Z1, X2, Y2, Z2, p):
        """add points with arbitrary z"""
        # after:
        # http://hyperelliptic.org/EFD/g1p/auto-shortw-jacobian.html#addition-add-2007-bl
        Z1Z1 = Z1 * Z1 % p
        Z2Z2 = Z2 * Z2 % p
        U1 = X1 * Z2Z2 % p
        U2 = X2 * Z1Z1 % p
        S1 = Y1 * Z2 * Z2Z2 % p
        S2 = Y2 * Z1 * Z1Z1 % p
        H = U2 - U1
        I = 4 * H * H % p
        J = H * I % p
        r = 2 * (S2 - S1) % p
        if not H and not r:
            return self._double(X1, Y1, Z1, p, self.__curve.a())
        V = U1 * I
        X3 = (r * r - J - 2 * V) % p
        Y3 = (r * (V - X3) - 2 * S1 * J) % p
        Z3 = ((Z1 + Z2) ** 2 - Z1Z1 - Z2Z2) * H % p

        return X3, Y3, Z3

    def __radd__(self, other):
        """Add other to self."""
        return self + other

    def _add(self, X1, Y1, Z1, X2, Y2, Z2, p):
        """add two points, select fastest method."""
        if not Y1 or not Z1:
            return X2, Y2, Z2
        if not Y2 or not Z2:
            return X1, Y1, Z1
        if Z1 == Z2:
            if Z1 == 1:
                return self._add_with_z_1(X1, Y1, X2, Y2, p)
            return self._add_with_z_eq(X1, Y1, Z1, X2, Y2, p)
        if Z1 == 1:
            return self._add_with_z2_1(X2, Y2, Z2, X1, Y1, p)
        if Z2 == 1:
            return self._add_with_z2_1(X1, Y1, Z1, X2, Y2, p)
        return self._add_with_z_ne(X1, Y1, Z1, X2, Y2, Z2, p)

    def __add__(self, other):
        """Add two points on elliptic curve."""
        if self == INFINITY:
            return other
        if other == INFINITY:
            return self
        if isinstance(other, Point):
            other = PointJacobi.from_affine(other)
        if self.__curve != other.__curve:
            raise ValueError("The other point is on different curve")

        p = self.__curve.p()
        X1, Y1, Z1 = self.__coords
        X2, Y2, Z2 = other.__coords

        X3, Y3, Z3 = self._add(X1, Y1, Z1, X2, Y2, Z2, p)

        if not Y3 or not Z3:
            return INFINITY
        return PointJacobi(self.__curve, X3, Y3, Z3, self.__order)

    def __rmul__(self, other):
        """Multiply point by an integer."""
        return self * other

    def _mul_precompute(self, other):
        """Multiply point by integer with precomputation table."""
        X3, Y3, Z3, p = 0, 0, 1, self.__curve.p()
        _add = self._add
        for X2, Y2 in self.__precompute:
            if other % 2:
                if other % 4 >= 2:
                    other = (other + 1) // 2
                    X3, Y3, Z3 = _add(X3, Y3, Z3, X2, -Y2, 1, p)
                else:
                    other = (other - 1) // 2
                    X3, Y3, Z3 = _add(X3, Y3, Z3, X2, Y2, 1, p)
            else:
                other //= 2

        if not Y3 or not Z3:
            return INFINITY
        return PointJacobi(self.__curve, X3, Y3, Z3, self.__order)

    def __mul__(self, other):
        """Multiply point by an integer."""
        if not self.__coords[1] or not other:
            return INFINITY
        if other == 1:
            return self
        if self.__order:
            # order*2 as a protection for Minerva
            other = other % (self.__order * 2)
        self._maybe_precompute()
        if self.__precompute:
            return self._mul_precompute(other)

        self = self.scale()
        X2, Y2, _ = self.__coords
        X3, Y3, Z3 = 0, 0, 1
        p, a = self.__curve.p(), self.__curve.a()
        _double = self._double
        _add = self._add
        # since adding points when at least one of them is scaled
        # is quicker, reverse the NAF order
        for i in reversed(self._naf(other)):
            X3, Y3, Z3 = _double(X3, Y3, Z3, p, a)
            if i < 0:
                X3, Y3, Z3 = _add(X3, Y3, Z3, X2, -Y2, 1, p)
            elif i > 0:
                X3, Y3, Z3 = _add(X3, Y3, Z3, X2, Y2, 1, p)

        if not Y3 or not Z3:
            return INFINITY

        return PointJacobi(self.__curve, X3, Y3, Z3, self.__order)

    def mul_add(self, self_mul, other, other_mul):
        """
        Do two multiplications at the same time, add results.

        calculates self*self_mul + other*other_mul
        """
        if other == INFINITY or other_mul == 0:
            return self * self_mul
        if self_mul == 0:
            return other * other_mul
        if not isinstance(other, PointJacobi):
            other = PointJacobi.from_affine(other)
        # when the points have precomputed answers, then multiplying them alone
        # is faster (as it uses NAF and no point doublings)
        self._maybe_precompute()
        other._maybe_precompute()
        if self.__precompute and other.__precompute:
            return self * self_mul + other * other_mul

        if self.__order:
            self_mul = self_mul % self.__order
            other_mul = other_mul % self.__order

        # (X3, Y3, Z3) is the accumulator
        X3, Y3, Z3 = 0, 0, 1
        p, a = self.__curve.p(), self.__curve.a()

        # as we have 6 unique points to work with, we can't scale all of them,
        # but do scale the ones that are used most often
        self.scale()
        X1, Y1, Z1 = self.__coords
        other.scale()
        X2, Y2, Z2 = other.__coords

        _double = self._double
        _add = self._add

        # with NAF we have 3 options: no add, subtract, add
        # so with 2 points, we have 9 combinations:
        # 0, -A, +A, -B, -A-B, +A-B, +B, -A+B, +A+B
        # so we need 4 combined points:
        mAmB_X, mAmB_Y, mAmB_Z = _add(X1, -Y1, Z1, X2, -Y2, Z2, p)
        pAmB_X, pAmB_Y, pAmB_Z = _add(X1, Y1, Z1, X2, -Y2, Z2, p)
        mApB_X, mApB_Y, mApB_Z = _add(X1, -Y1, Z1, X2, Y2, Z2, p)
        pApB_X, pApB_Y, pApB_Z = _add(X1, Y1, Z1, X2, Y2, Z2, p)
        # when the self and other sum to infinity, we need to add them
        # one by one to get correct result but as that's very unlikely to
        # happen in regular operation, we don't need to optimise this case
        if not pApB_Y or not pApB_Z:
            return self * self_mul + other * other_mul

        # gmp object creation has cumulatively higher overhead than the
        # speedup we get from calculating the NAF using gmp so ensure use
        # of int()
        self_naf = list(reversed(self._naf(int(self_mul))))
        other_naf = list(reversed(self._naf(int(other_mul))))
        # ensure that the lists are the same length (zip() will truncate
        # longer one otherwise)
        if len(self_naf) < len(other_naf):
            self_naf = [0] * (len(other_naf) - len(self_naf)) + self_naf
        elif len(self_naf) > len(other_naf):
            other_naf = [0] * (len(self_naf) - len(other_naf)) + other_naf

        for A, B in zip(self_naf, other_naf):
            X3, Y3, Z3 = _double(X3, Y3, Z3, p, a)

            # conditions ordered from most to least likely
            if A == 0:
                if B == 0:
                    pass
                elif B < 0:
                    X3, Y3, Z3 = _add(X3, Y3, Z3, X2, -Y2, Z2, p)
                else:
                    assert B > 0
                    X3, Y3, Z3 = _add(X3, Y3, Z3, X2, Y2, Z2, p)
            elif A < 0:
                if B == 0:
                    X3, Y3, Z3 = _add(X3, Y3, Z3, X1, -Y1, Z1, p)
                elif B < 0:
                    X3, Y3, Z3 = _add(X3, Y3, Z3, mAmB_X, mAmB_Y, mAmB_Z, p)
                else:
                    assert B > 0
                    X3, Y3, Z3 = _add(X3, Y3, Z3, mApB_X, mApB_Y, mApB_Z, p)
            else:
                assert A > 0
                if B == 0:
                    X3, Y3, Z3 = _add(X3, Y3, Z3, X1, Y1, Z1, p)
                elif B < 0:
                    X3, Y3, Z3 = _add(X3, Y3, Z3, pAmB_X, pAmB_Y, pAmB_Z, p)
                else:
                    assert B > 0
                    X3, Y3, Z3 = _add(X3, Y3, Z3, pApB_X, pApB_Y, pApB_Z, p)

        if not Y3 or not Z3:
            return INFINITY

        return PointJacobi(self.__curve, X3, Y3, Z3, self.__order)

    def __neg__(self):
        """Return negated point."""
        x, y, z = self.__coords
        return PointJacobi(self.__curve, x, -y, z, self.__order)


class Point(AbstractPoint):
    """A point on a short Weierstrass elliptic curve. Altering x and y is
    forbidden, but they can be read by the x() and y() methods."""

    def __init__(self, curve, x, y, order=None):
        """curve, x, y, order; order (optional) is the order of this point."""
        super(Point, self).__init__()
        self.__curve = curve
        if GMPY:
            self.__x = x and mpz(x)
            self.__y = y and mpz(y)
            self.__order = order and mpz(order)
        else:
            self.__x = x
            self.__y = y
            self.__order = order
        # self.curve is allowed to be None only for INFINITY:
        if self.__curve:
            assert self.__curve.contains_point(x, y)
        # for curves with cofactor 1, all points that are on the curve are
        # scalar multiples of the base point, so performing multiplication is
        # not necessary to verify that. See Section 3.2.2.1 of SEC 1 v2
        if curve and curve.cofactor() != 1 and order:
            assert self * order == INFINITY

    @classmethod
    def from_bytes(
        cls,
        curve,
        data,
        validate_encoding=True,
        valid_encodings=None,
        order=None,
    ):
        """
        Initialise the object from byte encoding of a point.

        The method does accept and automatically detect the type of point
        encoding used. It supports the :term:`raw encoding`,
        :term:`uncompressed`, :term:`compressed`, and :term:`hybrid` encodings.

        :param data: single point encoding of the public key
        :type data: :term:`bytes-like object`
        :param curve: the curve on which the public key is expected to lay
        :type curve: ecdsa.ellipticcurve.CurveFp
        :param validate_encoding: whether to verify that the encoding of the
            point is self-consistent, defaults to True, has effect only
            on ``hybrid`` encoding
        :type validate_encoding: bool
        :param valid_encodings: list of acceptable point encoding formats,
            supported ones are: :term:`uncompressed`, :term:`compressed`,
            :term:`hybrid`, and :term:`raw encoding` (specified with ``raw``
            name). All formats by default (specified with ``None``).
        :type valid_encodings: :term:`set-like object`
        :param int order: the point order, must be non zero when using
            generator=True

        :raises MalformedPointError: if the public point does not lay on the
            curve or the encoding is invalid

        :return: Point on curve
        :rtype: Point
        """
        coord_x, coord_y = super(Point, cls).from_bytes(
            curve, data, validate_encoding, valid_encodings
        )
        return Point(curve, coord_x, coord_y, order)

    def __eq__(self, other):
        """Return True if the points are identical, False otherwise.

        Note: only points that lay on the same curve can be equal.
        """
        if isinstance(other, Point):
            return (
                self.__curve == other.__curve
                and self.__x == other.__x
                and self.__y == other.__y
            )
        return NotImplemented

    def __ne__(self, other):
        """Returns False if points are identical, True otherwise."""
        return not self == other

    def __neg__(self):
        return Point(self.__curve, self.__x, self.__curve.p() - self.__y)

    def __add__(self, other):
        """Add one point to another point."""

        # X9.62 B.3:

        if not isinstance(other, Point):
            return NotImplemented
        if other == INFINITY:
            return self
        if self == INFINITY:
            return other
        assert self.__curve == other.__curve
        if self.__x == other.__x:
            if (self.__y + other.__y) % self.__curve.p() == 0:
                return INFINITY
            else:
                return self.double()

        p = self.__curve.p()

        l = (
            (other.__y - self.__y)
            * numbertheory.inverse_mod(other.__x - self.__x, p)
        ) % p

        x3 = (l * l - self.__x - other.__x) % p
        y3 = (l * (self.__x - x3) - self.__y) % p

        return Point(self.__curve, x3, y3)

    def __mul__(self, other):
        """Multiply a point by an integer."""

        def leftmost_bit(x):
            assert x > 0
            result = 1
            while result <= x:
                result = 2 * result
            return result // 2

        e = other
        if e == 0 or (self.__order and e % self.__order == 0):
            return INFINITY
        if self == INFINITY:
            return INFINITY
        if e < 0:
            return (-self) * (-e)

        # From X9.62 D.3.2:

        e3 = 3 * e
        negative_self = Point(self.__curve, self.__x, -self.__y, self.__order)
        i = leftmost_bit(e3) // 2
        result = self
        # print_("Multiplying %s by %d (e3 = %d):" % (self, other, e3))
        while i > 1:
            result = result.double()
            if (e3 & i) != 0 and (e & i) == 0:
                result = result + self
            if (e3 & i) == 0 and (e & i) != 0:
                result = result + negative_self
            # print_(". . . i = %d, result = %s" % ( i, result ))
            i = i // 2

        return result

    def __rmul__(self, other):
        """Multiply a point by an integer."""

        return self * other

    def __str__(self):
        if self == INFINITY:
            return "infinity"
        return "(%d,%d)" % (self.__x, self.__y)

    def double(self):
        """Return a new point that is twice the old."""

        if self == INFINITY:
            return INFINITY

        # X9.62 B.3:

        p = self.__curve.p()
        a = self.__curve.a()

        l = (
            (3 * self.__x * self.__x + a)
            * numbertheory.inverse_mod(2 * self.__y, p)
        ) % p

        x3 = (l * l - 2 * self.__x) % p
        y3 = (l * (self.__x - x3) - self.__y) % p

        return Point(self.__curve, x3, y3)

    def x(self):
        return self.__x

    def y(self):
        return self.__y

    def curve(self):
        return self.__curve

    def order(self):
        return self.__order


class PointEdwards(AbstractPoint):
    """Point on Twisted Edwards curve.

    Internally represents the coordinates on the curve using four parameters,
    X, Y, Z, T. They correspond to affine parameters 'x' and 'y' like so:

    x = X / Z
    y = Y / Z
    x*y = T / Z
    """

    def __init__(self, curve, x, y, z, t, order=None):
        """
        Initialise a point that uses the extended coordinates interanlly.
        """
        super(PointEdwards, self).__init__()
        self.__curve = curve
        if GMPY:  # pragma: no branch
            self.__coords = (mpz(x), mpz(y), mpz(z), mpz(t))
            self.__order = order and mpz(order)
        else:  # pragma: no branch
            self.__coords = (x, y, z, t)
            self.__order = order

    def x(self):
        """Return affine x coordinate."""
        X1, _, Z1, _ = self.__coords
        if Z1 == 1:
            return X1
        p = self.__curve.p()
        z_inv = numbertheory.inverse_mod(Z1, p)
        return X1 * z_inv % p

    def y(self):
        """Return affine y coordinate."""
        _, Y1, Z1, _ = self.__coords
        if Z1 == 1:
            return Y1
        p = self.__curve.p()
        z_inv = numbertheory.inverse_mod(Z1, p)
        return Y1 * z_inv % p

    def curve(self):
        """Return the curve of the point."""
        return self.__curve

    def order(self):
        return self.__order

    def scale(self):
        """
        Return point scaled so that z == 1.

        Modifies point in place, returns self.
        """
        X1, Y1, Z1, _ = self.__coords
        if Z1 == 1:
            return self

        p = self.__curve.p()
        z_inv = numbertheory.inverse_mod(Z1, p)
        x = X1 * z_inv % p
        y = Y1 * z_inv % p
        t = x * y % p
        self.__coords = (x, y, 1, t)
        return self

    def __eq__(self, other):
        """Compare for equality two points with each-other.

        Note: only points on the same curve can be equal.
        """
        x1, y1, z1, t1 = self.__coords
        if other is INFINITY:
            return not x1 or not t1
        if isinstance(other, PointEdwards):
            x2, y2, z2, t2 = other.__coords
        else:
            return NotImplemented
        if self.__curve != other.curve():
            return False
        p = self.__curve.p()

        # cross multiply to eliminate divisions
        xn1 = x1 * z2 % p
        xn2 = x2 * z1 % p
        yn1 = y1 * z2 % p
        yn2 = y2 * z1 % p
        return xn1 == xn2 and yn1 == yn2

    def __ne__(self, other):
        """Compare for inequality two points with each-other."""
        return not self == other

    def _add(self, X1, Y1, Z1, T1, X2, Y2, Z2, T2, p, a):
        """add two points, assume sane parameters."""
        # after add-2008-hwcd-2
        # from https://hyperelliptic.org/EFD/g1p/auto-twisted-extended.html
        # NOTE: there are more efficient formulas for Z1 or Z2 == 1
        A = X1 * X2 % p
        B = Y1 * Y2 % p
        C = Z1 * T2 % p
        D = T1 * Z2 % p
        E = D + C
        F = ((X1 - Y1) * (X2 + Y2) + B - A) % p
        G = B + a * A
        H = D - C
        if not H:
            return self._double(X1, Y1, Z1, T1, p, a)
        X3 = E * F % p
        Y3 = G * H % p
        T3 = E * H % p
        Z3 = F * G % p

        return X3, Y3, Z3, T3

    def __add__(self, other):
        """Add point to another."""
        if other == INFINITY:
            return self
        if (
            not isinstance(other, PointEdwards)
            or self.__curve != other.__curve
        ):
            raise ValueError("The other point is on a different curve.")

        p, a = self.__curve.p(), self.__curve.a()
        X1, Y1, Z1, T1 = self.__coords
        X2, Y2, Z2, T2 = other.__coords

        X3, Y3, Z3, T3 = self._add(X1, Y1, Z1, T1, X2, Y2, Z2, T2, p, a)

        if not X3 or not T3:
            return INFINITY
        return PointEdwards(self.__curve, X3, Y3, Z3, T3, self.__order)

    def __radd__(self, other):
        """Add other to self."""
        return self + other

    def _double(self, X1, Y1, Z1, T1, p, a):
        """Double the point, assume sane parameters."""
        # after "dbl-2008-hwcd"
        # from https://hyperelliptic.org/EFD/g1p/auto-twisted-extended.html
        # NOTE: there are more efficient formulas for Z1 == 1
        A = X1 * X1 % p
        B = Y1 * Y1 % p
        C = 2 * Z1 * Z1 % p
        D = a * A % p
        E = ((X1 + Y1) * (X1 + Y1) - A - B) % p
        G = D + B
        F = G - C
        H = D - B
        X3 = E * F % p
        Y3 = G * H % p
        T3 = E * H % p
        Z3 = F * G % p

        return X3, Y3, Z3, T3

    def double(self):
        """Return point added to itself."""
        X1, Y1, Z1, T1 = self.__coords

        if not X1 or not T1:
            return INFINITY

        p, a = self.__curve.p(), self.__curve.a()

        X3, Y3, Z3, T3 = self._double(X1, Y1, Z1, T1, p, a)

        if not X3 or not T3:
            return INFINITY
        return PointEdwards(self.__curve, X3, Y3, Z3, T3, self.__order)

    def __mul__(self, other):
        """Multiply point by an integer."""
        X2, Y2, Z2, T2 = self.__coords
        if not X2 or not T2 or not other:
            return INFINITY
        if other == 1:
            return self
        if self.__order:
            # order*2 as a protection for Minerva
            other = other % (self.__order * 2)

        X3, Y3, Z3, T3 = 0, 1, 1, 0  # INFINITY in extended coordinates
        p, a = self.__curve.p(), self.__curve.a()
        _double = self._double
        _add = self._add

        for i in reversed(self._naf(other)):
            X3, Y3, Z3, T3 = _double(X3, Y3, Z3, T3, p, a)
            if i < 0:
                X3, Y3, Z3, T3 = _add(X3, Y3, Z3, T3, -X2, Y2, Z2, -T2, p, a)
            elif i > 0:
                X3, Y3, Z3, T3 = _add(X3, Y3, Z3, T3, X2, Y2, Z2, T2, p, a)

        if not X3 or not T3:
            return INFINITY

        return PointEdwards(self.__curve, X3, Y3, Z3, T3, self.__order)


# This one point is the Point At Infinity for all purposes:
INFINITY = Point(None, None, None)
