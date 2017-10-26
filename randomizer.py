from randomtools.tablereader import (
    TableObject, get_global_label, tblpath, addresses, get_random_degree,
    mutate_normal, shuffle_normal)
from randomtools.utils import (
    classproperty, get_snes_palette_transformer,
    read_multi, write_multi, utilrandom as random)
from randomtools.interface import (
    get_outfile, get_seed, get_flags, get_activated_codes,
    run_interface, rewrite_snes_meta, clean_and_write, finish_interface)
from randomtools.itemrouter import ItemRouter
from collections import defaultdict
from os import path
from time import time
from collections import Counter


VERSION = 0
ALL_OBJECTS = None
DEBUG_MODE = False
OBJECT_MAPPINGS = defaultdict(set)

object_mappings_filename = path.join(tblpath, "object_mappings.txt")
for line in open(object_mappings_filename):
    line = line.strip()
    if not line or line[0] == '#':
        continue
    zone, sector, screen, pointer = line.split()
    zone, sector, screen = map(int, [zone, sector, screen])
    pointer = int(pointer, 0x10)
    OBJECT_MAPPINGS[zone, sector, screen].add(pointer)
    OBJECT_MAPPINGS[pointer].add((zone, sector, screen))


class EnemyObject(TableObject):
    flag = 'm'
    flag_description = "monsters"

class ManEntObject(TableObject):
    flag = 'o'
    flag_description = "mansion order"

    def cleanup(self):
        address = getattr(addresses, "mexit%s" % (self.mansion-6))
        f = open(get_outfile(), "r+b")
        f.seek(address)
        f.write(chr(self.index))
        f.seek(address+3)
        f.write(chr(self.index))
        f.close()

class ObjectObject(TableObject):
    flag = 'i'
    flag_description = "items"

    def __repr__(self):
        s = "{0:0>3} {5:0>4} {1:0>2} {2:0>2} {3:0>2} {4:0>2}".format(
            *[("%x" % v) for v in [self.index, self.x, self.y,
                                   self.object_type, self.object_data,
                                   self.pointer]])
        mappings = self.mappings
        if len(mappings) == 1:
            s += " (%s, %s, %s)" % (mappings[0])
        else:
            s += " (%s mappings)" % len(mappings)
        return s

    @property
    def mappings(self):
        return sorted(OBJECT_MAPPINGS[self.pointer])

    @classmethod
    def get_for_mapping(cls, zone, sector, screen):
        return [o for o in ObjectObject.every
                if o.pointer in OBJECT_MAPPINGS[zone, sector, screen]]

    @classmethod
    def get_by_pointer(cls, pointer):
        return [o for o in ObjectObject.every if o.pointer == pointer][0]

    @property
    def signature(self):
        return (self.object_type << 8) | self.object_data

    def set_item(self, signature):
        self.object_type = signature >> 8
        self.object_data = signature & 0xFF
        assert self.signature == signature


def print_screen_objects(zone, sector, screen):
    for o in ObjectObject.get_for_mapping(zone, sector, screen):
        print o


def find_together(objtypes):
    success = []
    for mapping in sorted(OBJECT_MAPPINGS.keys()):
        if isinstance(mapping, int):
            continue
        objects = ObjectObject.get_for_mapping(*mapping)
        these_objtypes = [o.object_type for o in objects]
        if set(these_objtypes) >= set(objtypes):
            success.append(mapping)
    return success


def route_items():
    ir = ItemRouter(path.join(tblpath, "requirements.txt"))
    pointers = [int(p, 0x10) for p in ir.assign_conditions
                if p not in ir.definitions]
    assert 0x5a65 not in pointers
    objs = [o for o in ObjectObject.every if o.pointer in pointers]
    assert len(objs) == len(pointers)
    aggression = 3

    # Must have dracula's heart for Braham (to reach the entrance)

    mansions = range(5)
    random.shuffle(mansions)
    if 'o' not in get_flags():
        mansions = sorted(mansions)

    mansion_conversion = dict(enumerate(mansions))
    mansion_pointers = {1: (0x5b45, 0x5b99),  # Berkeley
                        2: (0x5c47, 0x5c4b),  # Rover
                        3: (0x5ca0, 0x5ce3),  # Braham
                        4: (0x5f97, 0x5fab),  # Bodley
                        #4: (0x5a65, 0x5aa1, 0x5acb),  # Laruba
                        0: (0x5aa1, 0x5acb),  # Laruba
                        }

    # Must have white crystal for Berkeley (to navigate the mansion)
    new_berkeley = [k for (k, v) in mansion_conversion.items() if v == 1][0]
    pointers = mansion_pointers[new_berkeley]
    for p in pointers:
        p = "%x" % p
        conditions = ir.assign_conditions[p]
        ir.assign_conditions[p] = conditions + "&white_crystal"

    # Must have holy water for Bodley (to navigate the mansion)
    new_bodley = [k for (k, v) in mansion_conversion.items() if v == 4][0]
    pointers = mansion_pointers[new_bodley]
    for p in pointers:
        p = "%x" % p
        conditions = ir.assign_conditions[p]
        ir.assign_conditions[p] = conditions + "&holy_water"

    ir._assignable_cache = {}

    remains = [o for o in objs if o.object_type == 0x25]
    while True:
        random.shuffle(remains)
        # Braham can't contain Dracula's Heart
        if remains[2].object_data != 0x19:
            break

    labeldict = {
        "dracula_heart": 0x2519,
        "white_crystal": 0xae07,
        "blue_crystal": 0xaf03,
        "red_crystal": 0xaf04,
        "laurels": 0xae00,
        "holy_water": 0xae03,
        "stake": 0xae06,
        }
    for k, v in labeldict.items():
        assert v not in labeldict
        labeldict[v] = k

    remains_pointers = set([o.pointer for o in remains])
    custom_items = {}
    for m, o in enumerate(remains):
        pointers = remains_pointers & set(mansion_pointers[m])
        assert len(pointers) == 1
        pointer = list(pointers)[0]
        pointer = "%x" % pointer
        assert (pointer in ir.assign_conditions
                and pointer not in ir.assigned_locations)
        if o.signature in labeldict:
            custom_items[pointer] = labeldict[o.signature]
        else:
            custom_items[pointer] = "%x" % o.signature

    ir.set_custom_assignments(custom_items)
    assert len(remains) == len(mansions)

    ir.assign_everything(aggression=aggression)
    assigned_codes = []
    for item in sorted(ir.assigned_items):
        try:
            code = int(item, 0x10)
        except ValueError:
            code = labeldict[item]
        assigned_codes.append(code)

    remaining_objs = []
    for o in objs:
        if o.signature in assigned_codes:
            assigned_codes.remove(o.signature)
            continue
        remaining_objs.append(o)

    random.shuffle(remaining_objs)
    for ro in remaining_objs:
        item = "%x" % ro.signature
        ir.assign_item(item, aggression=1)

    for key, value in sorted(ir.assignments.items()):
        pointer = int(key, 0x10)
        try:
            signature = int(value, 0x10)
        except:
            signature = labeldict[value]
        assert isinstance(signature, int)
        for key in mansion_pointers:
            if pointer in mansion_pointers[key]:
                new_mansion = mansion_conversion[key]
                new_pointers = mansion_pointers[new_mansion]
                new_objs = [o for o in ObjectObject.every
                            if o.pointer in new_pointers]
                if (signature >> 8) == 0x25:
                    new_objs = [o for o in new_objs if o.object_type == 0x25]
                else:
                    new_objs = [o for o in new_objs if o.object_type != 0x25]
                assert len(new_objs) == 1
                pointer = new_objs[0].pointer
                break
        obj = ObjectObject.get_by_pointer(pointer)
        obj.set_item(signature)

    for me in ManEntObject.every:
        new_mansion = mansion_conversion[me.index]
        me.mansion = new_mansion + 6

    '''
    for (pointer, item) in sorted(ir.assignments.items()):
        try:
            int(item, 0x10)
        except ValueError:
            print pointer, item
    print sorted(mansion_conversion.items())
    '''


if __name__ == "__main__":
    try:
        print ("You are using the Castlevania 2 "
               "randomizer version %s." % VERSION)
        print

        ALL_OBJECTS = [g for g in globals().values()
                       if isinstance(g, type) and issubclass(g, TableObject)
                       and g not in [TableObject]]

        run_interface(ALL_OBJECTS, snes=False)
        hexify = lambda x: "{0:0>2}".format("%x" % x)
        numify = lambda x: "{0: >3}".format(x)
        minmax = lambda x: (min(x), max(x))

        route_items()

        clean_and_write(ALL_OBJECTS)
        finish_interface()

    except IOError, e:
        print "ERROR: %s" % e
        raw_input("Press Enter to close this program.")
