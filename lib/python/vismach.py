#    Copyright 2007 John Kasunich and Jeff Epler
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

import copy
import sys, rs274.OpenGLTk, signal, hal
import tkinter

from OpenGL.GL import *
from OpenGL.GLU import *
from math import *
import glnav
import hal
import linuxcnc
import os
s = linuxcnc.stat()

old_plotclear = False

# Checks the prefix passed to a 'Hal...' class and sets the instance prefix
# The prefix is used to access hal pins or status attributes
def check_prefix(self, prefix):
    checked_prefix = None
    if isinstance(prefix, type(hal)) or isinstance(prefix, linuxcnc.stat):
        # hal instance or status channel instance  passed
        checked_prefix = prefix
    elif isinstance(prefix, hal.component):
        # component instance passed, get the actual prefix from the API
        checked_prefix = prefix.getprefix()
    elif isinstance(prefix, str):
        # check if the passed string is a hal component prefix
        if hal.component_is_ready(prefix): # component prefix passed
            checked_prefix = prefix
    return checked_prefix

def get_pin_or_attribute_value(self, prefix, val):
    try:
        if isinstance(prefix, type(hal)):
            return hal.get_value(val)
        elif isinstance(prefix, linuxcnc.stat):
            s.poll()
            return eval('s.'+ val)
        elif isinstance(val, str) and hal.component_is_ready(prefix):
            return hal.get_value(prefix + '.' + val)
    except Exception as e:
        print("Vismach Error: Cannot get pin or attribute value %s,\n Error: %s"  % (val ,e))
        sys.exit()


# Responsible for parsing and serving arguments (values, pins/attributes, expressions)
class ArgsBase(object):
    def __init__(self, *args):
        if not hasattr(self, 'prefix'):
            self.prefix = None
        self._args = args

    def _parse_expression(self, expr):
        if '{' not in expr:
            # Not an expression so we can try to get the value right away
            value = get_pin_or_attribute_value(self, self.prefix, expr)
            return value
        else:
            # an expression needs to be parsed
            try:
                # Split the expression string and extract parts between curly brackets
                parts = expr.split("{")
                res = [p.split("}")[0] for p in parts if "}" in p]
                vals = []
                for r in res:
                    value = get_pin_or_attribute_value(self, self.prefix, r)
                    vals.append(str(value))
                # insert the values into the expression string
                for i in range(len(res)):
                    expr = expr.replace(('{'+res[i])+'}', vals[i])
                return eval(expr)
            except Exception as e:
                print("Vismach Error: Cannot evaluate expression %s,\n  Error: %s" % (expr ,e))
                sys.exit()

    def _get_value(self, v):
        if isinstance(v, str):
            if os.path.isdir(v):
                # filename from 'HalAsciiOBJ()' or 'HalAsciiSTL'
                return v
            elif self.prefix is not None:
                # we got some string that either IS or contains halpin(s) or status attributes
                return self._parse_expression(v)
            else:
                print("Vismach Error: No prefix passed but string argument %s is not a path." % (v))
                sys.exit()
        else:
            # no string argument passed so we so we just pass on the value what we got
            return v

    # this serves the current value for each stored argument
    def coords(self):
        if len(self._args) == 1:
            return list(map(self._get_value, self._args))[0]
        return list(map(self._get_value, self._args))


########################
#   Parts Collector    #
########################

class Collection(ArgsBase):
    def __init__(self, parts, *args):
        # check parts
        if parts is None:
            raise TypeError("Vismach Error: Must have at least one part.")
        if not isinstance(parts, list):
            parts = [parts]
        self.parts = parts
        for part in parts:
            if not hasattr(part, 'coords') and not hasattr(part, 'capture') and not hasattr(part, 'draw'):
                raise TypeError("Vismach Error: '%s' is not a valid part" % (part))
        self.parts = parts
        ArgsBase.__init__(self, *args)

    def traverse(self):
        if not isinstance(self.parts, list):
            self.parts = [self.parts]
        for p in self.parts:
            if hasattr(p, "apply"):
                p.apply()
            if hasattr(p, "capture"):
                p.capture()
            if hasattr(p, "draw"):
                p.draw()
            if hasattr(p, "traverse"):
                p.traverse()
            if hasattr(p, "unapply"):
                p.unapply()

    def volume(self):
        if hasattr(self, "vol") and self.vol != 0:
            vol = self.vol
        else:
            vol = sum(part.volume() for part in self.parts)
        #print "Collection.volume", vol
        return vol

    # a collection consisting of overlapping parts will have an incorrect
    # volume, because overlapping volumes will be counted twice.  If the
    # correct volume is known, it can be set using this method
    def set_volume(self,vol):
        self.vol = vol;


##########################
#   Part Manipulators    #
##########################

class Translate(Collection):
    def __init__(self, parts, x, y, z):
        self.parts = parts
        self.where = x, y, z

    def apply(self):
        glPushMatrix()
        glTranslatef(*self.where)

    def unapply(self):
        glPopMatrix()

class Scale(Collection):
    def __init__(self, parts, x, y, z):
        self.parts = parts
        self.scaleby = x, y, z

    def apply(self):
        glPushMatrix()
        glScalef(*self.scaleby)

    def unapply(self):
        glPopMatrix()

class HalTranslate(Collection, ArgsBase):
    def __init__(self, parts, prefix, var, x, y, z):
        self.parts = parts
        self.prefix = check_prefix(self, prefix)
        ArgsBase.__init__(self, var, x, y, z)

    def apply(self):
        v, x, y, z = self.coords()
        glPushMatrix()
        glTranslatef(x*v, y*v, z*v)

    def unapply(self):
        glPopMatrix()


class HalRotate(Collection, ArgsBase):
    def __init__(self, parts, prefix, var, th, x, y, z):
        self.parts = parts
        self.prefix = check_prefix(self, prefix)
        ArgsBase.__init__(self, var, th, x, y, z)

    def apply(self):
        v, th, x, y, z = self.coords()
        glPushMatrix()
        glRotatef(th * v, x, y, z)

    def unapply(self):
        glPopMatrix()


class Rotate(Collection):
    def __init__(self, parts, th, x, y, z):
        self.parts = parts
        self.where = th, x, y, z

    def apply(self):
        th, x, y, z = self.where
        glPushMatrix()
        glRotatef(th, x, y, z)

    def unapply(self):
        glPopMatrix()


class HalRotateEuler(Collection, ArgsBase):
    def __init__(self, parts, prefix, th1, th2, th3, order=123):
        self.parts = parts
        ArgsBase.__init__(self, prefix, th1, th2, th3, order)

    def apply(self):
        th1, th2, th3, order = self.coords()
        glPushMatrix()
        if order == 131:
            glRotatef(th1, 1, 0, 0)
            glRotatef(th2, 0, 0, 1)
            glRotatef(th3, 1, 0, 0)
        elif order == 121:
            glRotatef(th1, 1, 0, 0)
            glRotatef(th2, 0, 1, 0)
            glRotatef(th3, 1, 0, 0)
        elif order == 212:
            glRotatef(th1, 0, 1, 0)
            glRotatef(th2, 1, 0, 0)
            glRotatef(th3, 0, 1, 0)
        elif order == 232:
            glRotatef(th1, 0, 1, 0)
            glRotatef(th2, 0, 0, 1)
            glRotatef(th3, 0, 1, 0)
        elif order == 323:
            glRotatef(th1, 0, 0, 1)
            glRotatef(th2, 0, 1, 0)
            glRotatef(th3, 0, 0, 1)
        elif order == 313:
            glRotatef(th1, 0, 0, 1)
            glRotatef(th2, 1, 0, 0)
            glRotatef(th3, 0, 0, 1)
        elif order == 123:
            glRotatef(th1, 1, 0, 0)
            glRotatef(th2, 0, 1, 0)
            glRotatef(th3, 0, 0, 1)
        elif order == 132:
            glRotatef(th1, 1, 0, 0)
            glRotatef(th2, 0, 0, 1)
            glRotatef(th3, 0, 1, 0)
        elif order == 213:
            glRotatef(th1, 0, 1, 0)
            glRotatef(th2, 1, 0, 0)
            glRotatef(th3, 0, 0, 1)
        elif order == 231:
            glRotatef(th1, 0, 1, 0)
            glRotatef(th2, 0, 0, 1)
            glRotatef(th3, 1, 0, 0)
        elif order == 321:
            glRotatef(th1, 0, 0, 1)
            glRotatef(th2, 0, 1, 0)
            glRotatef(th3, 1, 0, 0)
        elif order == 312:
            glRotatef(th1, 0, 0, 1)
            glRotatef(th2, 1, 0, 0)
            glRotatef(th3, 0, 1, 0)

    def unapply(self):
        glPopMatrix()


class Track(Collection):
    '''move and rotate an object to point from one capture()'d
        coordinate system to another.
        we need "world" to convert coordinates from GL_MODELVIEW coordinates
        to our coordinate system'''
    def __init__(self, parts, position, target, world):
        self.parts = parts
        self.target = target
        self.position = position
        self.world2view = world

    def angle_to(self,x,y,z):
        '''returns polar coordinates in degrees to a point from the origin
        a rotates around the x-axis; b rotates around the y axis; r is the distance'''
        azimuth = atan2(y, x)*180/pi #longitude
        elevation = atan2(z, sqrt(x**2 + y**2))*180/pi
        radius = sqrt(x**2+y**2+z**2)
        return((azimuth, elevation, radius))

    def map_coords(self,tx,ty,tz,transform):
        # now we have to transform them to the world frame
        wx = tx*transform[0][0]+ty*transform[1][0]+tz*transform[2][0]+transform[3][0]
        wy = tx*transform[0][1]+ty*transform[1][1]+tz*transform[2][1]+transform[3][1]
        wz = tx*transform[0][2]+ty*transform[1][2]+tz*transform[2][2]+transform[3][2]
        return([wx,wy,wz])

    def apply(self):
        # make sure we have something to work with first
        if len(self.world2view.t) < 4:
            glPushMatrix()
            return
        view2world = invert(self.world2view.t)
        px, py, pz = self.position.t[3][:3]
        px, py, pz = self.map_coords(px,py,pz,view2world)
        tx, ty, tz = self.target.t[3][:3]
        tx, ty, tz = self.map_coords(tx,ty,tz,view2world)
        dx = tx - px; dy = ty - py; dz = tz - pz;
        (az,el,r) = self.angle_to(dx,dy,dz)
        if(hasattr(HUD, "debug_track") and HUD.debug_track == 1):
                HUD.strs = []
                HUD.strs += ["current coords: %3.4f %3.4f %3.4f " % (px, py, pz)]
                HUD.strs += ["target coords: %3.4f %3.4f %3.4f" %  (tx, ty, tz)]
                HUD.strs += ["az,el,r: %3.4f %3.4f %3.4f" %  (az,el,r)]
        glPushMatrix()
        glTranslatef(px,py,pz)
        glRotatef(az-90,0,0,1)
        glRotatef(el-90,1,0,0)

    def unapply(self):
                glPopMatrix()

# scales an object by the value of a halpin
class HalScale(Collection, ArgsBase):
    def __init__(self, parts, prefix, x, y, z, var):
        self.parts = parts
        self.prefix = check_prefix(self, prefix)
        ArgsBase.__init__(self, x, y, z, var)

    def apply(self):
        th1, th2, th3, order = self.coords()

    def apply(self):
        factor, x, y, z = self.coords()
        glPushMatrix()
        glScalef(x*factor,y*factor,z*factor)

    def unapply(self):
        glPopMatrix()


# shows an object if const=var and hides it otherwise, behavior can be changed
# using the optional arguments for scalefactors when true or false
class HalShow(Collection, ArgsBase):
    def __init__(self, parts, prefix, const, var, scaleby_true=1, scaleby_false=0):
        self.parts = parts
        self.prefix = check_prefix(self, prefix)
        ArgsBase.__init__(self, const, var, scaleby_true, scaleby_false)

    def apply(self):
        args = self.coords()
        const, var, s_t, s_f = args
        glPushMatrix()
        if const == var:
            glScalef(s_t, s_t, s_t)
        else:
            glScalef(s_f, s_f, s_f)

    def unapply(self):
        glPopMatrix()


# translates an object using a variable translation vector
# use scale=-1 to change direction
class HalVectorTranslate(Collection, ArgsBase):
    def __init__(self, parts, prefix, xvar, yvar, zvar, scale=1):
        self.parts = parts
        self.prefix = check_prefix(self, prefix)
        ArgsBase.__init__(self, xvar, yvar, zvar, scale)

    def apply(self):
        xvar, yvar, zvar, sc = self.coords()
        glPushMatrix()
        glTranslatef(sc*xvar, sc*yvar, sc*zvar)

    def unapply(self):
        glPopMatrix()


class HalVectorRotate(Collection, ArgsBase):
    def __init__(self, parts, prefix, var, th, x, y, z):
        self.parts = parts
        self.prefix = check_prefix(self, prefix)
        ArgsBase.__init__(self, xvar, yvar, zvar, scale)

    def apply(self):
        var, th, x, y, z = self.coords()
        glPushMatrix()
        glRotatef(th * var, x, y, z)

    def unapply(self):
        glPopMatrix()


######################
#   Part Creators    #
######################

class Color(Collection, ArgsBase):
    def __init__(self, arg1, arg2, glow=0):
        if not isinstance(arg1, list):
            arg1=[arg1]
        # legacy atribute order was (self, color, parts)
        if all(isinstance(item, (int, float)) for item in arg1):
            self.parts = arg2
            ArgsBase.__init__(self, arg1, glow)
        else:
            self.parts = arg1
            ArgsBase.__init__(self, arg2, glow)

    def apply(self):
        color, glow = self.coords()
        glPushAttrib(GL_LIGHTING_BIT)
        glMaterialfv(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE, color)
        if glow==1:
            glMaterialfv(GL_FRONT, GL_EMISSION, [1,1,0,1])
        else:
            glMaterialfv(GL_FRONT, GL_EMISSION, [0,0,0,1])

    def unapply(self):
        glPopAttrib()

class HalColor(Color):
    def __init__(self, prefix, parts, color, glow=0):
        self.prefix = check_prefix(self, prefix)
        Color.__init__(self, parts, color, glow)


# Draw an open cylinder from point_1 to point_2,# stretchfactor and radius are optional
class Line(ArgsBase):
    def __init__(self, x_start, y_start, z_start, x_end, y_end, z_end, stretch=1, r=5):
        ArgsBase.__init__(self, x_start, y_start, z_start, x_end, y_end, z_end, stretch, r)

    def cross(self, a, b):
        return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]

    # calculate polar coordinates in degrees
    # a rotates around the x-axis; b rotates around the y axis
    def polar(self, v, s):
        length = sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2]) * s
        axis = (1, 0, 0) if hypot(v[0], v[1]) < 0.001 else self.cross(v, (0, 0, 1))
        angle = -atan2(hypot(v[0], v[1]), v[2])*180/pi
        return (length, angle, axis)

    def draw(self):
        x1, y1, z1, x2, y2, z2, s, r = self.coords()
        v = [x2,y2,z2]
        length, angle, axis = self.polar(v, s)
        glPushMatrix()
        glTranslate(x1, y1, z1)
        glRotate(angle,*axis)
        gluCylinder(gluNewQuadric(), r, r, length, 32, 1)

    def unapply(self):
        glPopMatrix()

class HalLine(Line):
    def __init__(self, prefix, x_start, y_start, z_start, x_end, y_end, z_end, stretch=1, r=5):
        self.prefix = check_prefix(self, prefix)
        Line.__init__(self, x_start, y_start, z_start, x_end, y_end, z_end, stretch, r)


# draw a plane defined by it's normal vector(vx,vy,vz) origin at (x,y,z)
class PlaneFromNormal(ArgsBase):
    def __init__(self, x_orig, y_orig, z_orig, x_vec, y_vec, z_vec, quadrant_size=500):
        ArgsBase.__init__(self, x_orig, y_orig, z_orig, x_vec, y_vec, z_vec, quadrant_size)

    def cross(self, a, b):
        return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]

    # calculate polar coordinates in degrees
    # a rotates around the x-axis; b rotates around the y axis
    def polar(self, v):
        length = sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2])
        axis = (1, 0, 0) if hypot(v[0], v[1]) < 0.001 else self.cross(v, (0, 0, 1))
        angle = -atan2(hypot(v[0], v[1]), v[2])*180/pi
        return (length, angle, axis)

    def square(self,n, s):
        glBegin(GL_QUADS)
        glNormal3f(n[0],n[1],n[2])
        glVertex3f( s,  s, 0)
        glVertex3f(-s,  s, 0)
        glVertex3f(-s, -s, 0)
        glVertex3f( s, -s, 0)
        glEnd()

    def draw(self):
        x, y, z, vx, vy, vz, s = self.coords()
        v = [vx, vy, vz]
        length, angle, axis = self.polar(v)
        glPushMatrix()
        glTranslate(x,y,z)
        glRotate(angle,*axis)
        self.square(v,s)

    def unapply(self):
        glPopMatrix()

class HalPlaneFromNormal(PlaneFromNormal):
    def __init__(self, prefix,  x, y, z, vx, vy, vz, s=500):
        self.prefix = check_prefix(self, prefix)
        PlaneFromNormal.__init__(self,  x, y, z, vx, vy, vz, s)


# draw a coordinate system defined by it's normal vector(zx,zy,zz) and x-direction vector(xx, xy, xz)
# optional r to define the thickness of the cylinders
class CoordsFromNormalAndDirection(ArgsBase):
    def __init__(self, x_orig, y_orig, z_orig, vec_Xx, vec_Xy, vec_Xz, vec_Zx, vec_Zy, vec_Zz, stretchfactor=1, radius=5):
        ArgsBase.__init__(self, x_orig, y_orig, z_orig, vec_Xx, vec_Xy, vec_Xz, vec_Zx, vec_Zy, vec_Zz, stretchfactor, radius)

    def draw_vector(self, r, stretch, color):
        gluCylinder(gluNewQuadric(), r, r, 50 * stretch, 32, 1)
        glMaterialfv(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE, color)

    def cross(self, a, b):
        return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]

    def draw(self):
        ox, oy, oz, xx, xy, xz, zx, zy, zz, stretch, r = self.coords()
        vo = [ox, oy, oz]
        vx = [xx, xy, xz]
        vz = [zx, zy, zz]
        # calculate the missing y vector
        vy = [yx, yy, yz] = self.cross(vz,vx)
        # for some reason we need to rotate in the opposite (transpose) sense
        m_t=[[ xx, xy, xz, 0],
             [ yx, yy, yz, 0],
             [ zx, zy, zz, 0],
             [ ox, oy, oz, 1]]
        glPushMatrix()
        glMultMatrixf(m_t)
        self.draw_vector(r, stretch, [1,0,0,1])
        glRotate(90,0,1,0)
        self.draw_vector(r, stretch, [0,1,0,1])
        glRotate(-90,1,0,0)
        self.draw_vector(r, stretch, [0,0,1,1])

    def unapply(self):
        glPopMatrix()

class HalCoordsFromNormalAndDirection(CoordsFromNormalAndDirection):
    def __init__(self, prefix, ox, oy, oz, xx, xy, xz, zx, zy, zz, stretch=1, r=5):
        self.prefix = check_prefix(self, prefix)
        CoordsFromNormalAndDirection.__init__(self, ox, oy, oz, xx, xy, xz, zx, zy, zz, stretch, r)


# draw a grid defined by it's normal vector(zx,zy,zz) and x-direction vector(xx, xy, xz)
# optional s to define the half-width from the origin (ox,oy,oz)
class GridFromNormalAndDirection(ArgsBase):
    def __init__(self, x_orig, y_orig, z_orig, vec_Xx, vec_Xy, vec_Xz, vec_Zx, vec_Zy, vec_Zz, quadrant_size=500):
        ArgsBase.__init__(self, x_orig, y_orig, z_orig, vec_Xx, vec_Xy, vec_Xz, vec_Zx, vec_Zy, vec_Zz, quadrant_size)

    def square(self, s):
        glBegin(GL_LINES);
        for i in range (-s,s+10,10):
            # line 1 in x direction
            glVertex3f(-s, i, 0)
            glVertex3f( s, i, 0)
            # line 1 in y direction
            glVertex3f( i,-s, 0)
            glVertex3f( i, s, 0)
        glEnd()

    def cross(self, a, b):
        return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]

    def draw(self):
        ox, oy, oz, xx, xy, xz, zx, zy, zz, s = self.coords()
        vo = [ox, oy, oz]
        vx = [xx, xy, xz]
        vz = [zx, zy, zz]
        # calculate the missing y vector
        vy = [yx, yy, yz] = self.cross(vz,vx)
        # for some reason we need to rotate in the opposite (transpose) sense
        m_t=[[ xx, xy, xz, 0],
             [ yx, yy, yz, 0],
             [ zx, zy, zz, 0],
             [ ox, oy, oz, 1]]
        glPushMatrix()
        glMultMatrixf(m_t)
        self.square(s)

    def unapply(self):
        glPopMatrix()

class HalGridFromNormalAndDirection(GridFromNormalAndDirection):
    def __init__(self, prefix, ox, oy, oz, xx, xy, xz, zx, zy, zz, s=500):
        self.prefix = check_prefix(self, prefix)
        GridFromNormalAndDirection.__init__(self, ox, oy, oz, xx, xy, xz, zx, zy, zz, s)


# draw a grid defined by it's normal vector(vx,vy,vz) origin at (x,y,z)
class GridFromNormal(ArgsBase):
    def __init__(self, x_orig, y_orig, z_orig, x_vec, y_vec, z_vec, quadrant_size=500):
        ArgsBase.__init__(self, x_orig, y_orig, z_orig, x_vec, y_vec, z_vec, quadrant_size)

    def cross(self, a, b):
        return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]

    # calculate polar coordinates in degrees
    # a rotates around the x-axis; b rotates around the y axis
    def polar(self, v):
        length = sqrt(v[0]*v[0] + v[1]*v[1] + v[2]*v[2])
        axis = (1, 0, 0) if hypot(v[0], v[1]) < 0.001 else self.cross(v, (0, 0, 1))
        angle = -atan2(hypot(v[0], v[1]), v[2])*180/pi
        return (length, angle, axis)

    def square(self,n, s):
        glBegin(GL_LINES);
        for i in range (-s,s+10,10):
            # line 1 in x direction
            glVertex3f(-s, i, 0)
            glVertex3f( s, i, 0)
            # line 1 in y direction
            glVertex3f( i,-s, 0)
            glVertex3f( i, s, 0)
        glEnd()

    def draw(self):
        x, y, z, vx, vy, vz, s = self.coords()
        v = [vx, vy, vz]
        length, angle, axis = self.polar(v)
        glPushMatrix()
        glTranslate(x,y,z)
        glRotate(angle,*axis)
        self.square(v,s)

    def unapply(self):
        glPopMatrix()

class HalGridFromNormal(GridFromNormal):
    def __init__(self, prefix, ox, oy, oz, vx, vy, vz, s=500):
        self.prefix = check_prefix(self, prefix)
        GridFromNormal.__init__(self, prefix, ox, oy, oz, vx, vy, vz, s)


# draw a grid
class Grid(ArgsBase):
    def __init__(self, quadrant_size=500):
        ArgsBase.__init__(self, quadrant_size)

    def grid(self, s):
        glBegin(GL_LINES);
        for i in range (-s,s+10,10):
            # line 1 in x direction
            glVertex3f(-s, i, 0)
            glVertex3f( s, i, 0)
            # line 1 in y direction
            glVertex3f( i,-s, 0)
            glVertex3f( i, s, 0)
        glEnd()

    def draw(self):
        s = self.coords()
        self.grid(s)

class HalGrid(Grid):
    def __init__(self, prefix, s=500):
        self.prefix = check_prefix(self, prefix)
        Grid.__init__(self, s)


class CylinderZ(ArgsBase):
    def __init__(self, z_start, r_start, z_end, r_end):
        ArgsBase.__init__(self, z_start, r_start, z_end, r_end)

    def draw(self):
        z1, r1, z2, r2 = self.coords()
        if z1 > z2:
            tmp = z1
            z1 = z2
            z2 = tmp
            tmp = r1
            r1 = r2
            r2 = tmp
        # need to translate the whole thing to z1
        glPushMatrix()
        if hasattr(self, 'orient'):
            self.orient()
        glTranslatef(0,0,z1)
        # the cylinder starts out at Z=0
        gluCylinder(gluNewQuadric(), r1, r2, z2-z1, 32, 1)
        # bottom cap
        glRotatef(180,1,0,0)
        gluDisk(gluNewQuadric(), 0, r1, 32, 1)
        glRotatef(180,1,0,0)
        # the top cap needs flipped and translated
        glPushMatrix()
        glTranslatef(0,0,z2-z1)
        gluDisk(gluNewQuadric(), 0, r2, 32, 1)
        glPopMatrix()
        glPopMatrix()

    def volume(self):
        z1, r1, z2, r2 = self.coords()
        # actually a frustum of a cone
        vol = 3.1415927/3.0 * abs(z1-z2)*(r1*r1+r1*r2+r2*r2)
        #print "CylinderZ.volume", vol
        return vol

class HalCylinderZ(CylinderZ):
    def __init__(self, prefix, z_start, r_start, z_end, r_end):
        self.prefix = check_prefix(self, prefix)
        CylinderZ.__init__(self, z_start, r_start, z_end, r_end)


# give endpoint Y values and radii
# resulting cylinder is on the Y axis
class CylinderY(CylinderZ):
    def __init__(self, y_start, r_start, y_end, r_end):
        ArgsBase.__init__(self, y_start, r_start, y_end, r_end)

    def orient(self):
        glRotatef(-90,1,0,0)


class HalCylinderY(CylinderY):
    def __init__(self, prefix, y_start, r_start, y_end, r_end):
        self.prefix = check_prefix(self, prefix)
        CylinderY.__init__(self, y_start, r_start, y_end, r_end)


# give endpoint X values and radii
# resulting cylinder is on the X axis
class CylinderX(CylinderZ):
    def __init__(self, x_start, r_start, x_end, r_end):
        ArgsBase.__init__(self, x_start, r_start, x_end, r_end)

    def orient(self):
        glRotatef(90,0,1,0)


class HalCylinderX(CylinderX):
    def __init__(self, prefix, x_start, r_start, x_end, r_end):
        self.prefix = check_prefix(self, prefix)
        CylinderX.__init__(self, x_start, r_start, x_end, r_end)


# give center and radius
class Sphere(ArgsBase):
    def __init__(self, x_center, y_center, z_center, radius):
        ArgsBase.__init__(self, x_center, y_center, z_center, radius)

    def draw(self):
        x, y, z, r = self.coords()
        # need to translate the whole thing to x,y,z
        glPushMatrix()
        glTranslatef(x,y,z)
        # the sphere starts out at the origin
        gluSphere(gluNewQuadric(), r, 32, 16)
        glPopMatrix()

    def volume(self):
        x, y, z, r = self.coords()
        vol = 1.3333333*3.1415927*r*r*r
        #print "Sphere.volume", vol
        return vol

class HalSphere(Sphere):
    def __init__(self, prefix, x_center, y_center, z_center, radius):
        self.prefix = check_prefix(self, prefix)
        Sphere.__init__(self, x_center, y_center, z_center, radius)


# triangular plate in XY plane
# specify the corners Z values for each side
class TriangleXY(ArgsBase):
    def __init__(self, x1, y1, x2, y2, x3, y3, z1, z2):
        ArgsBase.__init__(self, x1, y1, x2, y2, x3, y3, z1, z2)

    def draw(self):
        x1, y1, x2, y2, x3, y3, z1, z2 = self.coords()
        x12 = x1-x2
        y12 = y1-y2
        x13 = x1-x3
        y13 = y1-y3
        cross = x12*y13 - x13*y12
        if cross < 0:
            tmp = x2
            x2 = x3
            x3 = tmp
            tmp = y2
            y2 = y3
            y3 = tmp
        if z1 > z2:
            tmp = z1
            z1 = z2
            z2 = tmp
        x12 = x1-x2
        y12 = y1-y2
        x23 = x2-x3
        y23 = y2-y3
        x31 = x3-x1
        y31 = y3-y1
        glBegin(GL_QUADS)
        # side 1-2
        h = hypot(x12,y12)
        glNormal3f(-y12/h,x12/h,0)
        glVertex3f(x1, y1, z1)
        glVertex3f(x2, y2, z1)
        glVertex3f(x2, y2, z2)
        glVertex3f(x1, y1, z2)
        # side 2-3
        h = hypot(x23,y23)
        glNormal3f(-y23/h,x23/h,0)
        glVertex3f(x2, y2, z1)
        glVertex3f(x3, y3, z1)
        glVertex3f(x3, y3, z2)
        glVertex3f(x2, y2, z2)
        # side 3-1
        h = hypot(x31,y31)
        glNormal3f(-y31/h,x31/h,0)
        glVertex3f(x3, y3, z1)
        glVertex3f(x1, y1, z1)
        glVertex3f(x1, y1, z2)
        glVertex3f(x3, y3, z2)
        glEnd()
        glBegin(GL_TRIANGLES)
        # upper face
        glNormal3f(0,0,1)
        glVertex3f(x1, y1, z2)
        glVertex3f(x2, y2, z2)
        glVertex3f(x3, y3, z2)
        # lower face
        glNormal3f(0,0,-1)
        glVertex3f(x1, y1, z1)
        glVertex3f(x3, y3, z1)
        glVertex3f(x2, y2, z1)
        glEnd()

    def volume(self):
        x1, y1, x2, y2, x3, y3, z1, z2 = self.coords()
        # compute pts 2 and 3 relative to 1 (puts pt1 at origin)
        x2 = x2-x1
        x3 = x3-x1
        y2 = y2-y1
        y3 = y3-y1
        # compute area of triangle
        area = 0.5*abs(x2*y3 - x3*y2)
        thk = abs(z1-z2)
        vol = area*thk
        #print "TriangleXY.volume = area * thickness)",vol, area, thk
        return vol

class HalTriangleXY(TriangleXY):
    def __init__(self,prefix, x1, y1, x2, y2, x3, y3, z1, z2):
        self.prefix = check_prefix(self, prefix)
        TriangleXY.__init__(self, x1, y1, x2, y2, x3, y3, z1, z2)

# triangular plate in XZ plane
class TriangleXZ(TriangleXY):
    def coords(self):
        x1, z1, x2, z2, x3, z3, y1, y2 = TriangleXY.coords(self)
        return x1, z1, x2, z2, x3, z3, -y1, -y2

    def draw(self):
        glPushMatrix()
        glRotatef(90,1,0,0)
        # create the triangle in XY plane
        TriangleXY.draw(self)
        # bottom cap
        glPopMatrix()

    def volume(self):
        vol = TriangleXY.volume(self)
        #print " TriangleXZ.volume",vol
        return vol

class HalTriangleXZ(TriangleXZ):
    def __init__(self, prefix, *args):
        self.prefix = check_prefix(self, prefix)
        TriangleXZ.__init__(args)

# triangular plate in YZ plane
class TriangleYZ(TriangleXY):
    def coords(self):
        y1, z1, y2, z2, y3, z3, x1, x2 = TriangleXY.coords(self)
        return z1, y1, z2, y2, z3, y3, -x1, -x2

    def draw(self):
        glPushMatrix()
        glRotatef(90,0,-1,0)
        # create the triangle in XY plane
        TriangleXY.draw(self)
        # bottom cap
        glPopMatrix()

    def volume(self):
        vol = TriangleXY.volume(self)
        #print " TriangleYZ.volume",vol
        return vol

class HalTriangleYZ(TriangleYZ):
    def __init__(self, prefix, *args):
        self.prefix = check_prefix(self, prefix)
        TriangleYZ.__init__(args)


# pipe segment along X, inner radius (r1), outer radius (r1), start angle (a1), end angle (a2)
class ArcX(ArgsBase):
    def __init__(self, x1, x2, r1, r2, a1, a2, steps):
        ArgsBase.__init__(self, x1, x2, r1, r2, a1, a2, steps)

    def draw(self):
        x1, x2, r1, r2, a1, a2, steps = self.coords()
        if x1 > x2:
            tmp = x1
            x1 = x2
            x2 = tmp
        if r1 > r2:
            tmp = r1
            r1 = r2
            r2 = tmp
        while a1 > a2:
            a2 = a2 + 360
        astep = ((a2-a1)/steps)*(pi/180)
        a1rads = a1 * (pi/180)
        # positive X end face
        glBegin(GL_QUAD_STRIP)
        glNormal3f(1,0,0)
        n = 0
        while n <= steps:
            angle = a1rads+n*astep
            s = sin(angle)
            c = cos(angle)
            glVertex3f(x2, r1*s, r1*c)
            glVertex3f(x2, r2*s, r2*c)
            n = n + 1

        glEnd()
        # negative X end face
        glBegin(GL_QUAD_STRIP)
        glNormal3f(-1,0,0)
        n = 0
        while n <= steps:
            angle = a1rads+n*astep
            s = sin(angle)
            c = cos(angle)
            glVertex3f(x1, r1*s, r1*c)
            glVertex3f(x1, r2*s, r2*c)
            n = n + 1
        glEnd()
        # inner diameter
        glBegin(GL_QUAD_STRIP)
        n = 0
        while n <= steps:
            angle = a1rads+n*astep
            s = sin(angle)
            c = cos(angle)
            glNormal3f(0,-s, -c)
            glVertex3f(x1, r1*s, r1*c)
            glVertex3f(x2, r1*s, r1*c)
            n = n + 1
        glEnd()
        # outer diameter
        glBegin(GL_QUAD_STRIP)
        n = 0
        while n <= steps:
            angle = a1rads+n*astep
            s = sin(angle)
            c = cos(angle)
            glNormal3f(0, s, c)
            glVertex3f(x1, r2*s, r2*c)
            glVertex3f(x2, r2*s, r2*c)
            n = n + 1
        glEnd()
        # end plates
        glBegin(GL_QUADS)
        # first end plate
        angle = a1 * (pi/180)
        s = sin(angle)
        c = cos(angle)
        glNormal3f(0, -c, s)
        glVertex3f(x1, r2*s, r2*c)
        glVertex3f(x2, r2*s, r2*c)
        glVertex3f(x2, r1*s, r1*c)
        glVertex3f(x1, r1*s, r1*c)
        # other end
        angle = a2 * (pi/180)
        s = sin(angle)
        c = cos(angle)
        glNormal3f(0, c, -s)
        glVertex3f(x1, r2*s, r2*c)
        glVertex3f(x2, r2*s, r2*c)
        glVertex3f(x2, r1*s, r1*c)
        glVertex3f(x1, r1*s, r1*c)
        glEnd()

    def volume(self):
        x1, x2, r1, r2, a1, a2, steps = self.coords()
        if x1 > x2:
            tmp = x1
            x1 = x2
            x2 = tmp
        if r1 > r2:
            tmp = r1
            r1 = r2
            r2 = tmp
        while a1 > a2:
            a2 = a2 + 360
        height = x2 - x1
        angle = a2 - a1
        area = (angle/360.0)*pi*(r2*r2-r1*r1)
        vol = area * height
        #print "Arc.volume = angle * area * height",vol, angle, area, height
        return vol

class HalArcX(ArcX):
    def __init__(self,prefix, x1, x2, r1, r2, a1, a2, steps):
        self.prefix = check_prefix(self, prefix)
        ArcX.__init__(self, x1, x2, r1, r2, a1, a2, steps)


# six coordinate version - specify each side of the box
class Box(ArgsBase):
    def __init__(self, x1, y1, z1, x2, y2, z2):
        ArgsBase.__init__(self, x1, y1, z1, x2, y2, z2)

    def draw(self):
        x1, y1, z1, x2, y2, z2 = self.coords()
        if x1 > x2:
            tmp = x1
            x1 = x2
            x2 = tmp
        if y1 > y2:
            tmp = y1
            y1 = y2
            y2 = tmp
        if z1 > z2:
            tmp = z1
            z1 = z2
            z2 = tmp

        glBegin(GL_QUADS)
        # bottom face
        glNormal3f(0,0,-1)
        glVertex3f(x2, y1, z1)
        glVertex3f(x1, y1, z1)
        glVertex3f(x1, y2, z1)
        glVertex3f(x2, y2, z1)
        # positive X face
        glNormal3f(1,0,0)
        glVertex3f(x2, y1, z1)
        glVertex3f(x2, y2, z1)
        glVertex3f(x2, y2, z2)
        glVertex3f(x2, y1, z2)
        # positive Y face
        glNormal3f(0,1,0)
        glVertex3f(x1, y2, z1)
        glVertex3f(x1, y2, z2)
        glVertex3f(x2, y2, z2)
        glVertex3f(x2, y2, z1)
        # negative Y face
        glNormal3f(0,-1,0)
        glVertex3f(x2, y1, z2)
        glVertex3f(x1, y1, z2)
        glVertex3f(x1, y1, z1)
        glVertex3f(x2, y1, z1)
        # negative X face
        glNormal3f(-1,0,0)
        glVertex3f(x1, y1, z1)
        glVertex3f(x1, y1, z2)
        glVertex3f(x1, y2, z2)
        glVertex3f(x1, y2, z1)
        # top face
        glNormal3f(0,0,1)
        glVertex3f(x1, y2, z2)
        glVertex3f(x1, y1, z2)
        glVertex3f(x2, y1, z2)
        glVertex3f(x2, y2, z2)
        glEnd()

    def volume(self):
        x1, y1, z1, x2, y2, z2 = self.coords()
        vol = abs((x1-x2)*(y1-y2)*(z1-z2))
        #print "Box.volume", vol
        return vol

class HalBox(Box):
    def __init__(self, prefix, x1, y1, z1, x2, y2, z2):
        self.prefix = check_prefix(self, prefix)
        Box.__init__(self, x1, y1, z1, x2, y2, z2)

# specify the width in X and Y, and the height in Z
# the box is centered on the origin
class BoxCentered(Box):
    def __init__(self, xw, yw, zw):
        Box.__init__(self, -xw/2.0, -yw/2.0, -zw/2.0, xw/2.0, yw/2.0, zw/2.0)

class HalBoxCentered(Box):
    def __init__(self, prefix, xw, yw, zw):
        self.prefix = check_prefix(self, prefix)
        Box.__init__(self, -xw/2.0, -yw/2.0, -zw/2.0, xw/2.0, yw/2.0, zw/2.0)


# specify the width in X and Y, and the height in Z
# the box is centered in X and Y, and runs from Z=0 up
# (or down) to the specified Z value
class BoxCenteredXY(Box):
    def __init__(self, xw, yw, zw):
        Box.__init__(self, -xw/2.0, -yw/2.0, 0, xw/2.0, yw/2.0, zw)

class HalBoxCenteredXY(Box):
    def __init__(self, prefix, xw, yw, zw):
        self.prefix = check_prefix(self, prefix)
        Box.__init__(self, -xw/2.0, -yw/2.0, 0, xw/2.0, yw/2.0, zw)


# capture current transformation matrix
# note that this transforms from the current coordinate system
# to the viewport system, NOT to the world system
class Capture(object):
    def __init__(self):
        self.t = []
        self.tracked_parts = [self]

    def capture(self):
        self.t = glGetDoublev(GL_MODELVIEW_MATRIX)

    def volume(self):
        return 0.0


# function to invert a transform matrix
# based on http://steve.hollasch.net/cgindex/math/matrix/afforthinv.c
# with simplifications since we don't do scaling

# This function inverts a 4x4 matrix that is affine and orthogonal.  In
# other words, the perspective components are [0 0 0 1], and the basis
# vectors are orthogonal to each other.  In addition, the matrix must
# not do scaling

def invert(src):
        # make a copy
        inv=copy.deepcopy(src)
        # The inverse of the upper 3x3 is the transpose (since the basis
        # vectors are orthogonal to each other.
        inv[0][1],inv[1][0] = inv[1][0],inv[0][1]
        inv[0][2],inv[2][0] = inv[2][0],inv[0][2]
        inv[1][2],inv[2][1] = inv[2][1],inv[1][2]
        # The inverse of the translation component is just the negation
        # of the translation after dotting with the new upper3x3 rows. */
        inv[3][0] = -(src[3][0]*inv[0][0] + src[3][1]*inv[1][0] + src[3][2]*inv[2][0])
        inv[3][1] = -(src[3][0]*inv[0][1] + src[3][1]*inv[1][1] + src[3][2]*inv[2][1])
        inv[3][2] = -(src[3][0]*inv[0][2] + src[3][1]*inv[1][2] + src[3][2]*inv[2][2])
        return inv


# head up display - draws a semi-transparent text box.
class Hud(object):
        def __init__(self, showme=1):
            self.app = []
            self.strs = []
            self.messages = []
            self.fontbase = []
            self.hud_lines = []
            self.show_tags = []
            self.hide_alls = []
            self.hud_rgba_r = 0
            self.hud_rgba_g = 0.2
            self.hud_rgba_b = 0
            self.hud_rgba_a = 0.5
            self.hud_text_rgb_r = 1
            self.hud_text_rgb_g = 0.8
            self.hud_text_rgb_b = 0.4
            self.hide_hud = showme == 0

        # legacy function, unconditionally hides the overlay
        def hide(self):
            self.hide_hud = True

        # legacy function, no longer supported, use add_txt() with a tag instead
        def clear(self):
            print("vismach.py, Hud.clear() deprecated, use add_txt() with a tag instead ")

        # legacy vismach models used this
        def show(self, string):
            self.hide_hud = False
            self.add_txt(string)

        # displays a string, optionally a tag or list of tags can be assigned
        def add_txt(self, string, tag=None):
            prefix=None
            self.hud_lines += [[str(string), None, tag, prefix]]

        # displays a formatted pin or status value (can be embedded in a string)
        # defaults to a general hal pin for status use (prefix= <linuxcnc.stat instance>)
        def add_pin(self, string, pin=None, tag=None, prefix=hal):
            self.hud_lines += [[str(string), pin, tag, prefix]]

        # shows all lines with the specified tag if the pin value = val
        def show_tag_if_same(self, tag, pin, val=True):
            self.show_tags += [[tag, pin, val]]

        # shows all lines with a tag equal to the pin value + offset
        def show_tags_in_pin(self, pin, offs=0):
            self.show_tags += [[pin, None, offs]]

        # hides the complete hud if the pin value is equal to val
        def hide_all(self, pin, val=True):
            self.hide_alls += [[pin, val]]

        # changes the hud color and transparency
        def set_hud_rgba(self, r, g, b, a):
            self.hud_rgba_r = r
            self.hud_rgba_g = g
            self.hud_rgba_b = b
            self.hud_rgba_a = a

        # changes the hud text color
        def set_hud_text_rgb(self, r, g, b):
            self.hud_text_rgb_r = r
            self.hud_text_rgb_g = g
            self.hud_text_rgb_b = b

        # update the lines in the hud using the lists created above
        def draw(self):
            messages = []
            show_list = [None]
            # check if hud should be hidden
            hide_hud_requested = False
            for a in self.hide_alls:
                if hal.get_value(a[0]) == a[1]:
                    hide_hud_requested = True
            if not self.hide_hud and not hide_hud_requested:
                # create list of all line tags to be shown
                for b in self.show_tags:
                    tag = None
                    if b[1] == None: # _show_tags_in_pin
                        tag = int(hal.get_value(b[0]) + b[2])
                    else: # _show_tag_if_same
                        if  hal.get_value(b[1]) == b[2]:
                            tag = b[0]
                    if not isinstance(tag, list):
                        tag = [tag]
                    if tag is not None:
                        show_list = show_list + tag
                # create list of message lines to be shown
                for hud_line in self.hud_lines:
                    #print("++++",hud_line)
                    [string, pin, tag, prefix] = hud_line
                    if not isinstance(tag, list):
                        tag = [tag]
                    if any(item in tag for item in show_list):
                        if pin == None: # text
                            messages += [string]
                        else : # pin or status
                            value = get_pin_or_attribute_value(self, prefix, pin)
                            messages += [string.format(value)]
                drawtext = self.strs + messages

                # draw head-up-display
                # see axis.py for more font/color configurability
                if len(drawtext) == 0:
                    return

                glMatrixMode(GL_PROJECTION)
                glPushMatrix()
                glLoadIdentity()

                if not self.fontbase:
                        self.fontbase = int(self.app.loadbitmapfont("9x15"))
                char_width, char_height = 9, 15
                xmargin,ymargin = 5,5
                ypos = float(self.app.winfo_height())

                glOrtho(0.0, self.app.winfo_width(), 0.0, ypos, -1.0, 1.0)
                glMatrixMode(GL_MODELVIEW)
                glPushMatrix()
                glLoadIdentity()

                # draw the text box
                maxlen = max([len(p) for p in drawtext])
                box_width = maxlen * char_width
                glDepthFunc(GL_ALWAYS)
                glDepthMask(GL_FALSE)
                glDisable(GL_LIGHTING)
                glEnable(GL_BLEND)
                glEnable(GL_NORMALIZE)
                glBlendFunc(GL_ONE, GL_CONSTANT_ALPHA)
                # sets the color of the hud overlay
                glColor3f(self.hud_rgba_r, self.hud_rgba_g, self.hud_rgba_b)
                # rgba, sets the transparency of the overlay using the 'a' value
                glBlendColor(0,0,0,self.hud_rgba_a)
                glBegin(GL_QUADS)
                glVertex3f(0, ypos, 1) #upper left
                glVertex3f(0, ypos - 2*ymargin - char_height*len(drawtext), 1) #lower left
                glVertex3f(box_width+2*xmargin, ypos - 2*ymargin - char_height*len(drawtext), 1) #lower right
                glVertex3f(box_width+2*xmargin,  ypos , 1) #upper right
                glEnd()
                glDisable(GL_BLEND)
                glEnable(GL_LIGHTING)

                # fill the box with text
                maxlen = 0
                ypos -= char_height+ymargin
                i = 0
                glDisable(GL_LIGHTING)
                # sets the color of the text in the hud
                glColor3f(self.hud_text_rgb_r, self.hud_text_rgb_g, self.hud_text_rgb_b)
                for string in drawtext:
                        maxlen = max(maxlen, len(string))
                        glRasterPos2i(xmargin, int(ypos))
                        for char in string:
                                glCallList(self.fontbase + ord(char))
                        ypos -= char_height
                        i = i + 1
                glDepthFunc(GL_LESS)
                glDepthMask(GL_TRUE)
                glEnable(GL_LIGHTING)

                glPopMatrix()
                glMatrixMode(GL_PROJECTION)
                glPopMatrix()
                glMatrixMode(GL_MODELVIEW)




class O(rs274.OpenGLTk.Opengl):
    def __init__(self, *args, **kw):
        rs274.OpenGLTk.Opengl.__init__(self, *args, **kw)
        self.r_back = self.g_back = self.b_back = 0
        #self.q1 = gluNewQuadric()
        #self.q2 = gluNewQuadric()
        #self.q3 = gluNewQuadric()
        self.plotdata = []
        self.plotlen = 16000
        #does not show HUD by default
        self.hud = Hud()

    def basic_lighting(self):
        self.activate()
        glLightfv(GL_LIGHT0, GL_POSITION, (1, -1, .5, 0))
        glLightfv(GL_LIGHT0, GL_AMBIENT, (.2,.2,.2,0))
        glLightfv(GL_LIGHT0, GL_DIFFUSE, (.6,.6,.4,0))
        glLightfv(GL_LIGHT0+1, GL_POSITION, (-1, -1, .5, 0))
        glLightfv(GL_LIGHT0+1, GL_AMBIENT, (.0,.0,.0,0))
        glLightfv(GL_LIGHT0+1, GL_DIFFUSE, (.0,.0,.4,0))
        glMaterialfv(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE, (1,1,1,0))
        glDisable(GL_CULL_FACE)
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glEnable(GL_LIGHT0+1)
        glDepthFunc(GL_LESS)
        glEnable(GL_DEPTH_TEST)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()

    def redraw(self, *args):
        if self.winfo_width() == 1: return
        self.model.traverse()
        # current coords: world
        # the matrices tool2view, work2view, and world2view
        # transform from tool/work/world coords to viewport coords
        # if we want to draw in tool coords, we need to do
        # "tool -> view -> world" (since the current frame is world)
        # and if we want to draw in work coords, we need
        # "work -> view -> world".  For both, we need to invert
        # the world2view matrix to do the second step
        view2world = invert(self.world2view.t)
        # likewise, for backplot, we want to transform the tooltip
        # position from tool coords (where it is [0,0,0]) to work
        # coords, so we need tool -> view -> work
        # so lets also invert the work2view matrix
        view2work = invert(self.work2view.t)

        # since backplot lines only need vertices, not orientation,
        # and the tooltip is at the origin, getting the tool coords
        # is easy
        tx, ty, tz = self.tool2view.t[3][:3]
        # now we have to transform them to the work frame
        wx = tx*view2work[0][0]+ty*view2work[1][0]+tz*view2work[2][0]+view2work[3][0]
        wy = tx*view2work[0][1]+ty*view2work[1][1]+tz*view2work[2][1]+view2work[3][1]
        wz = tx*view2work[0][2]+ty*view2work[1][2]+tz*view2work[2][2]+view2work[3][2]
        # wx, wy, wz are the values to use for backplot
        # so we save them in a buffer
        if len(self.plotdata) == self.plotlen:
            del self.plotdata[:self.plotlen / 10]
        point = [ wx, wy, wz ]
        if not self.plotdata or point != self.plotdata[-1]:
            self.plotdata.append(point)

        # now lets draw something in the tool coordinate system
        #glPushMatrix()
        # matrixes take effect in reverse order, so the next
        # two lines do "tool -> view -> world"
        #glMultMatrixd(view2world)
        #glMultMatrixd(self.tool2view.t)

        # do drawing here
        # cylinder normally goes to +Z, we want it down
        #glTranslatef(0,0,-60)
        #gluCylinder(self.q1, 20, 20, 60, 32, 16)

        # back to world coords
        #glPopMatrix()


        # we can also draw in the work coord system
        glPushMatrix()
        # "work -> view -> world"
        glMultMatrixd(view2world)
        glMultMatrixd(self.work2view.t)
        # now we can draw in work coords, and whatever we draw
        # will move with the work, (if the work is attached to
        # a table or indexer or something that moves with
        # respect to the world

        # just a test object, sitting on the table
        #gluCylinder(self.q2, 40, 20, 60, 32, 16)

        #draw head up display
        if(hasattr(self.hud, "draw")):
                self.hud.draw()

        # draw backplot
        glDisable(GL_LIGHTING)
        glLineWidth(2)
        glColor3f(1.0,0.5,0.5)

        glBegin(GL_LINE_STRIP)
        for p in self.plotdata:
            glVertex3f(*p)
        glEnd()

        glEnable(GL_LIGHTING)
        glColor3f(1,1,1)
        glLineWidth(1)
        glDisable(GL_BLEND)
        glDepthFunc(GL_LESS)

        # back to world again
        glPopMatrix()

    def plotclear(self):
        del self.plotdata[:self.plotlen]


class AsciiSTL:
    def __init__(self, filename=None, data=None):
        self.load(filename, data)

    def load(self, filename, data):
        if data is None:
            data = open(filename, "r")
        elif isinstance(data, str):
            data = data.split("\n")
        self.list = None
        t = []
        n = [0,0,0]
        self.d = d = []
        for line in data:
            if line.find("normal") != -1:
                line = line.split()
                x, y, z = list(map(float, line[-3:]))
                n = [x,y,z]
            elif line.find("vertex") != -1:
                line = line.split()
                x, y, z = list(map(float, line[-3:]))
                t.append([x,y,z])
                if len(t) == 3:
                    if n == [0,0,0]:
                        dx1 = t[1][0] - t[0][0]
                        dy1 = t[1][1] - t[0][1]
                        dz1 = t[1][2] - t[0][2]
                        dx2 = t[2][0] - t[0][0]
                        dy2 = t[2][1] - t[0][1]
                        dz2 = t[2][2] - t[0][2]
                        n = [dy1*dz2 - dy2*dz1, dz1*dx2 - dz2*dx1, dy1*dx2 - dy2*dx1]
                    d.append((n, t))
                    t = []
                    n = [0,0,0]

    def draw(self):
        if self.list is None:
            # OpenGL isn't ready yet in __init__ so the display list
            # is created during the first draw
            self.list = glGenLists(1)
            glNewList(self.list, GL_COMPILE)
            glBegin(GL_TRIANGLES)
            for n, t in self.d:
                glNormal3f(*n)
                glVertex3f(*t[0])
                glVertex3f(*t[1])
                glVertex3f(*t[2])
            glEnd()
            glEndList()
            del self.d
        glCallList(self.list)

class HalAsciiSTL(AsciiSTL, ArgsBase):
    def __init__(self, prefix, filename=None, path='', data=None):
        self.explicit_path = None
        if os.path.isfile(path + filename):
            self.explicit_path = path + filename
            self.load(self.explicit_path, data)
        else:
            # No explicit filepath has been passed so we'll need to query for the value
            self.prefix = check_prefix(self, prefix)
            self.old_filepath = None
            self.error_path = None
            ArgsBase.__init__(self, filename, path, data)

    def draw(self):
        if self.explicit_path is not None:
            AsciiSTL.draw(self)
        else:
            filename, path, data = self.coords()
            # filename is an integer here as we get it from a halpin or a status attribute
            self.filepath = path + str(filename) + '.stl'
            if self.filepath != self.old_filepath:
                self.old_filepath = self.filepath
                if not os.path.isfile(self.filepath):
                    # If the file is not there we want to print a message, but only once
                    if self.filepath != self.error_path:
                        print('Vismach Error: Unable to read file ', filepath)
                    self.error_path = filepath
                else:
                    self.load(filepath, data)
                    self.error_path = None
            if self.error_path is None:
                AsciiSTL.draw(self)



class AsciiOBJ:
    def __init__(self, filename=None, data=None):
        self.load(filename, data)

    def load(self, filename, data):
        if data is None:
            data = open(filename, "r")
        elif isinstance(data, str):
            data = data.split("\n")
        self.v = v = []
        self.vn = vn = []
        self.f = f = []
        for line in data:
            if line.startswith("#"): continue
            if line.startswith("vn"):
                vn.append([float(w) for w in line.split()[1:]])
            elif line.startswith("v"):
                v.append([float(w) for w in line.split()[1:]])
            elif line.startswith("f"):
                f.append(self.parse_face(line))
        self.list = None

    def parse_int(self, i):
        if i == '': return None
        return int(i)

    def parse_slash(self, word):
        return [self.parse_int(i) for i in word.split("/")]

    def parse_face(self, line):
        return [self.parse_slash(w) for w in line.split()[1:]]

    def draw(self):
        if self.list is None:
            # OpenGL isn't ready yet in __init__ so the display list
            # is created during the first draw
            self.list = glGenLists(1)
            glNewList(self.list, GL_COMPILE)
            glDisable(GL_CULL_FACE)
            glBegin(GL_TRIANGLES)
            #print "obj", len(self.f)
            for f in self.f:
                for v, t, n in f:
                    if n:
                        glNormal3f(*self.vn[n-1])
                    glVertex3f(*self.v[v-1])
            glEnd()
            glEndList()
            del self.v
            del self.vn
            del self.f
        glCallList(self.list)


class HalAsciiOBJ(AsciiOBJ, ArgsBase):
    def __init__(self, prefix, filename=None, path='', data=None):
        self.explicit_path = None
        if os.path.isfile(path + filename):
            self.explicit_path = path + filename
            self.load(self.explicit_path, data)
        else:
            # No explicit filepath has been passed so we'll need to query for the value
            self.prefix = check_prefix(self, prefix)
            self.old_filepath = None
            self.error_path = None
            ArgsBase.__init__(self, filename, path, data)

    def draw(self):
        if self.explicit_path is not None:
            AsciiOBJ.draw(self)
        else:
            filename, path, data = self.coords()
            # filename is an integer here as we get it from a halpin or a status attribute
            self.filepath = path + str(filename) + '.stl'
            if self.filepath != self.old_filepath:
                self.old_filepath = self.filepath
                if not os.path.isfile(self.filepath):
                    # If the file is not there we want to print a message, but only once
                    if self.filepath != self.error_path:
                        print('Vismach Error: Unable to read file ', filepath)
                    self.error_path = filepath
                else:
                    self.load(filepath, data)
                    self.error_path = None
            if self.error_path is None:
                AsciiOBJ.draw(self)


def main(model, tool, work, size=10, hud=0, rotation_vectors=None, lat=0, lon=0):
    app = tkinter.Tk()
    t = O(app, double=1, depth=1)
    # set which axes to rotate around
    if rotation_vectors: t.rotation_vectors = rotation_vectors
    # we want to be able to see the model from all angles
    t.set_latitudelimits(-180, 180)
    # set starting viewpoint if desired
    t.after(100, lambda: t.set_viewangle(lat, lon, forcerotate=1))

    vcomp = hal.component("vismach")
    vcomp.newpin("plotclear",hal.Type.BOOL,hal.Dir.IN)
    vcomp.ready()

    #there's probably a better way of doing this
    global HUD
    HUD = 0
    if(hud != 0 and hasattr(hud, "app")):
            HUD = hud
                #point our app at the global
            t.hud = HUD

    t.hud.app = t #HUD needs to know where to draw

    # need to capture the world coordinate system
    world = Capture()

    t.model = Collection([model, world])
    t.distance = size * 3
    t.near = size * 0.01
    t.far = size * 10.0
    t.tool2view = tool
    t.world2view = world
    t.work2view = work

    t.pack(fill="both", expand=1)

    def update():
        global old_plotclear
        t.tkRedraw()
        new_plotclear = vcomp["plotclear"]
        if new_plotclear and not old_plotclear:
            t.plotclear()
        old_plotclear=new_plotclear
        t.after(100, update)
    update()

    def quit(*args):
        raise SystemExit

    signal.signal(signal.SIGTERM, quit)
    signal.signal(signal.SIGINT, quit)

    app.mainloop()
