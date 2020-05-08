


def get_doc_fix(script, symbol) -> str:

    doc = {
        "nwscript": {
            "GetObjectByTagAndType": ("Broken", "Always returns OBJECT_INVALID"),
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
                - The action is aborted if path toward the destination is blocked (by a door, another creature, etc.)
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
                Does not properly display AOE if creator is the Module or an Area. Use a placeable, creature or waypoint instead to create it.
                """),
            "CreateObject": ("Note", """
                Does not work for creatures if the location is not walkable (i.e. GetIsLocationValid returns FALSE). You can use CalcSafeLocation to find a good spot for spawning the creature.
                """),
        }
    }.get(script, {}).get(symbol, None)

    if doc is not None:
        color = {
            "Broken": "#f00",
            "Warning": "#ff0",
            "Note": "#888",
        }.get(doc[0], "#fff")

        return ('<div style="border-left: 0.5em solid %s; padding-left: 1em">' % color
                 + '<h3 style="color: %s">%s</h3>' % (color, doc[0])
                 + '<p>%s</p>' % doc[1]
                 + '</div>'
        )

    return None
