


def get_doc_fix(script, symbol) -> str:
    return {
        "nwscript": {
            "SetFog": ("Broken", "Does nothing"),
            "EffectDisintegrate": ("Broken", "Does nothing"),
            "EffectDisappearAppear": ("Broken", "Creature does not reappear at passed in location"),
            "EffectDisappear": ("Broken", "Does not perform the animation"),
            "EffectAppear": ("Broken", "Does not perform the animation"),
            "EffectNWN2ParticleEffect": ("Broken", "Does nothing"),
            "EffectNWN2ParticleEffectFile": ("Broken", "Does nothing"),
            "OpenInventory": ("Broken", "Does nothing"),
            "GetItemAppearance": ("Broken", "Does nothing"),
            "CopyItemAndModify": ("Broken", "Does nothing"),
            "SetTileMainLightColor": ("Broken", "Does nothing"),
            "SetTileSourceLightColor": ("Broken", "Does nothing"),
            "RecomputeStaticLighting": ("Broken", "Does nothing"),
            "GetTileMainLight1Color": ("Broken", "Does nothing"),
            "GetTileMainLight2Color": ("Broken", "Does nothing"),
            "GetTileSourceLight1Color": ("Broken", "Does nothing"),
            "GetTileSourceLight2Color": ("Broken", "Does nothing"),
            "SetPanelButtonFlash": ("Broken", "Does nothing"),
            "MountObject": ("Broken", "Does nothing"),
            "DismountObject": ("Broken", "Does nothing"),
            "GetLastRespawnButtonPresser": ("Broken", "Does nothing"),
            "SetPlaceableIllumination": ("Broken", "Does nothing"),
            "GetPlaceableIllumination": ("Broken", "Does nothing"),
            "EffectTimeStop": ("Broken", "Does nothing"),
            "GetCasterClassSpellSchool": ("Broken", "Aborts the script execution, and crashes the server in some conditions"),

            "GetObjectByTagAndType": ("Warning", """
                nObjectType parameter does not use OBJECT_TYPE constants. You must instead use the following constants:<br>
                AREA = 0x04          CREATURE = 0x05  ITEM = 0x06<br>
                TRIGGER = 0x07       PLACEABLE = 0x09 DOOR = 0x0A<br>
                AREAOFEFFECT = 0x0B  WAYPOINT = 0x0C  ENCOUNTER = 0x0D<br>
                STORE = 0x0E         SOUND = 0x10     STATIC_CAMERA = 0x12<br>
                ENV_OBJECT = 0x13    TREE = 0x14      LIGHT = 0x15<br>
                PLACED_EFFECT = 0x16<br>
                <small>GUI = 0x01 TILE = 0x02 MODULE = 0x03 PROJECTILE = 0x08 DYNAMIC = 0x11 PORTAL = 0x0F</small>
                """),
            "GetDescription": ("Warning", """
                GetDescription will return "" if the description has not been previously set with SetDescription
                """),
            "StringToObject": ("Warning", """
                StringToObject only converts decimal values and does not handle Hex values that are returned by ObjectToString.
                """),
            "ObjectToString": ("Warning", """
                Use IntToString(ObjectToInt(oValue)) instead if you plan on converting this value back to object later using StringToObject.
                """),
            "EffectCutsceneGhost": ("Warning", """
                Use SetCollision instead if you don't want the creature to collide with other objects
                """),
            "GetDamageDealtByType": ("Warning", """
                DAMAGE_TYPE_SLASHING, DAMAGE_TYPE_PIERCING and DAMAGE_TYPE_BLUDGEONING does not work.<br>
                You can write a function to deduce physical damage by subtracting each damage dealt by type from GetTotalDamageDealt.
                """),
            "ItemPropertyDamageResistance": ("Warning", """
                DAMAGE_TYPE_SLASHING, DAMAGE_TYPE_PIERCING and DAMAGE_TYPE_BLUDGEONING does not work (UI chat logs indicates absorption, underlying HP values do not)
                """),
            "EffectDamageResistance": ("Warning", """
                DAMAGE_TYPE_SLASHING, DAMAGE_TYPE_PIERCING and DAMAGE_TYPE_BLUDGEONING does not work (UI chat logs indicates absorption, underlying HP values do not)
                """),
            "ActionSit": ("Warning", """
                PC moves two steps towards chair, but not all the way, and does not perform sitting animation on it.
                """),
            "SetWeather": ("Warning", """
                Does not work for WEATHER_TYPE_SNOW or WEATHER_TYPE_LIGHTNING
                """),
            "SetEventHandler": ("Warning", """
                Does not work for module or Area Objects
                """),
            "GetEventHandler": ("Warning", """
                Does not work for module or Area Objects
                """),
            "ActionPlayAnimation": ("Warning", """
                Does not loop a looping animation for the full time period specified by fDurationSeconds.
                """),
            "AddItemProperty": ("Warning", """
                Does not work with ItemPropertyDamageReduction. Use EffectDamageReduction instead if possible.
                """),
            "GetFirstName": ("Warning", """
                Does not return toolset-edited FirstName value, will return correct value but only after SetFirstName has been called. Use GetName to get both the first and last name.
                """),
            "DayToNight": ("Warning", """
                Does not  work. Displays/removes stars but does not change lighting & skybox. Use SetTime to advance time instead.
                """),
            "NightToDay": ("Warning", """
                Does not  work. Displays/removes stars but does not change lighting & skybox. Use SetTime to advance time instead.
                """),
            "GetResRef": ("Warning", """
                Does not work for waypoints, stores, sounds, and areas.
                """),
            "ForceRest": ("Warning", """
                Does not trigger poison and disease saving throw stages
                """),
            "SignalEvent": ("Warning", """
                Does not work for AOE object's user defined events
                """),
            "ActionUseSkill": ("Warning", """
                Does not work for all skills (Taunt, SetTrap)
                """),
            "ActionCastSpellAtObject": ("Warning", """
                - nMetaMagic parameter does not work.<br>
                - If bCheat == TRUE, does not set correctly the caster level
                """),
            "ActionCastSpellAtLocation": ("Warning", """
                - nMetaMagic parameter does not work.<br>
                - If bCheat == TRUE, does not set correctly the caster level
                """),
            "ActionMoveToObject": ("Warning", """
                - Does not move the creature to another area<br>
                - The action is aborted if path toward the destination is blocked (by a door, another creature, etc.)<br>
                ActionForceMoveToObject is an alternative that assures the creature always reaches the destination after a certain delay.
                """),
            "ActionMoveToLocation": ("Warning", """
                - Does not move the creature to another area<br>
                - The action is aborted if path toward the destination is blocked (by a door, another creature, etc.)
                """),
            "GetHasSpell": ("Warning", """
                Broken for the Summon Creature I-IX spells.
                """),
            "SetIsTemporaryEnemy": ("Warning", """
                Makes oTarget a temporary enemy of oSource, not the other way round as documented below.
                """),
            "CopyItem": ("Warning", """
                The 'Appearance (visual effect)' property will not be copied to the returned item.
                """),
            "GetFirstObjectInShape": ("Warning", """
                Make sure the area of lTarget is a valid area object, otherwise this function will <strong>crash the server</strong>.
                """),
            "GetStandardFactionReputation": ("Warning", """
                Make sure oCreature is valid, otherwise this function will abort the script execution.
                """),
            "GetBicFileName": ("Warning", """
                Make sure that oPC is a valid object, otherwise this function will <strong>crash the server</strong>.
                """),
            "PlayCustomAnimation": ("Warning", """
                fSpeed does not appear to work.<br>
                <br>
                Some characters have special meanings:<br>
                <b>%</b> Idle animation / reset looping animation<br>
                <b>*1attack01</b>: Play $model_$stance_1attack01<br>
                <b>una_1attack01</b>: Play $model_una_1attack01<br>
                """),
            "EffectBonusHitpoints": ("Warning", """
                Make sure nHitpoints > 0, otherwise this function will crash the server.
                """),
            "EffectSetScale": ("Warning", """
                This function substract <code>(1 - fScaleN)</code> to the object scale (as reported by GetScale). A resulting scale of 0 in any axis can cause client issues and should be avoided.
                """),

            "AddListBoxRow": ("Note", """
                sHideUnhide parameter uses <b>show</b> and <b>hide</b> values to show/hide elements
                """),
            "ActionRest": ("Note", """
                Ignores bIgnoreNoRest parameter (does not ignore AREA no rest flag, but does ignore nearby hostile creatures)
                """),
            "SetDescription": ("Note", """
                Does not change the description text of an object that is currently examined. Close and re-open examine GUI to prevent that.
                """),
            "GetclassByPosition": ("Note", """
                Does not return CLASS_TYPE_INVALID when given OBJECT_INVALID.
                """),
            "ItemPropertySkillBonus": ("Note", """
                Does not work with SKILL_ALL_SKILLS constant. Use a loop to add each skill individually.
                """),
            "EffectAreaOfEffect": ("Note", """
                Does not properly display AOE if creator is the Module or an Area. Use a placeable, creature or waypoint instead to create it.<br>
                See vfx_persistent.2da for adding custom shapes.
                """),
            "CreateObject": ("Note", """
                Does not work for creatures if the location is not walkable (i.e. GetIsLocationValid returns FALSE). You can use CalcSafeLocation to find a good spot for spawning the creature.
                """),
            "FloatingTextStringOnCreature": ("Note", """
                The colors can be specified as hexadecimal values: 0xFFFFFF for white, 0xFF0000 for red, etc.
                """),
            "FloatingTextStrRefOnCreature": ("Note", """
                The colors can be specified as hexadecimal values: 0xFFFFFF for white, 0xFF0000 for red, etc.
                """),
            "FadeToBlack": ("Note", """
                nColor can be specified as hexadecimal value: 0xFFFFFF for white, 0xFF0000 for red, etc.
                """),
            "GetArea": ("Note", """
                Returns OBJECT_INVALID if oTarget is an item in the inventory, or the module, or an invalid object.<br>
                Returns oTarget if oTarget is an area.
                """),
            "GetIsLocationValid": ("Note", """
                Checks if the location is <strong>walk-able</strong>. To check if the location is valid use GetIsObjectValid(GetAreaFromLocation(lLocation)).
                """),
            "GetSpellId": ("Note", """
                Can be used outside of spell scripts, as long as the effect was either created in a spell script or its spell ID was set using SetEffectSpellId.
                """),
            "SetScale": ("Note", """
                Also works with negative values ;)
                """),
        }
    }.get(script, {}).get(symbol, None)
