import { describe, expect, it } from 'vitest'
import { distance, duration, gameMode, itemName, num, placement, weaponName } from './format'

describe('duration', () => {
  it('formats minutes and seconds, and hours past an hour', () => {
    expect(duration(0)).toBe('0m 00s')
    expect(duration(65)).toBe('1m 05s')
    expect(duration(3600)).toBe('1h 00m')
    expect(duration(5430)).toBe('1h 30m')
  })

  it('distinguishes zero from absent', () => {
    // A player who survived 0 s is not a player with no recorded time, and a
    // match strip that renders one as the other is lying about the data.
    expect(duration(0)).toBe('0m 00s')
    expect(duration(null)).toBe('—')
    expect(duration(undefined)).toBe('—')
  })

  it('never renders a negative duration', () => {
    expect(duration(-5)).toBe('0m 00s')
  })
})

describe('num', () => {
  it('groups thousands and honours the requested precision', () => {
    expect(num(1234)).toBe('1,234')
    expect(num(1234.567, 1)).toBe('1,234.6')
    expect(num(0)).toBe('0')
  })

  it('renders absent values as a dash, not as zero', () => {
    expect(num(null)).toBe('—')
    expect(num(undefined)).toBe('—')
    expect(num(NaN)).toBe('—')
  })
})

describe('gameMode', () => {
  it('capitalises words and upper-cases the perspective', () => {
    expect(gameMode('squad-fpp')).toBe('Squad FPP')
    expect(gameMode('duo-fpp')).toBe('Duo FPP')
    expect(gameMode('solo')).toBe('Solo')
  })

  it('never throws on an empty or absent mode', () => {
    // This threw. `''.split('-')` is `[''],` so `p[0]` was undefined and
    // `p[0]!.toUpperCase()` blew up — during render, inside the replay's
    // TopBar, which passes '' while the match query is in flight. React
    // Router's error boundary then swallowed the entire page, canvas and all.
    expect(() => gameMode('')).not.toThrow()
    expect(gameMode('')).toBe('—')
    expect(gameMode(null)).toBe('—')
    expect(gameMode(undefined)).toBe('—')
  })

  it('survives malformed separators', () => {
    // Every PUBG enum is open; a formatter must not assume its input's shape.
    expect(() => gameMode('-')).not.toThrow()
    expect(() => gameMode('squad--fpp')).not.toThrow()
    expect(gameMode('squad--fpp')).toBe('Squad FPP')
    expect(() => gameMode('brand-new-mode-2')).not.toThrow()
  })
})

describe('weaponName', () => {
  it('strips PUBG class-name decoration', () => {
    expect(weaponName('WeapHK416_C')).toBe('HK416')
    expect(weaponName('Item_Weapon_AWM_C')).toBe('AWM')
  })

  it('always renders something for an unknown id', () => {
    // api-assets froze in Oct 2024 and ~11% of live ids are missing from it.
    // A miss must degrade to the raw id, never to an empty cell.
    expect(weaponName('SomethingBrandNew_C')).toBe('SomethingBrandNew')
    expect(weaponName('totally-unknown')).not.toBe('')
  })

  it('renders a dash for a genuinely absent weapon', () => {
    // A zone or fall death has no weapon at all — 2.9% of kills.
    expect(weaponName(null)).toBe('—')
    expect(weaponName(undefined)).toBe('—')
    expect(weaponName('')).toBe('—')
    // Six kills store the literal string "None" — a stringified Python null.
    // It is absence, and must not reach the screen as a weapon called "None".
    expect(weaponName('None')).toBe('—')
  })

  /**
   * Every id below was copied verbatim out of the corpus, not invented:
   *   select weapon, count(*) from kill_events
   *   where weapon not like 'Weap%' group by weapon order by 2 desc;
   *
   * They are ~5% of all kills, and the plain decoration-stripping path
   * rendered them `ProjGrenade`, `PlayerFemale A` and `Uaz B 01`.
   */
  it('names the damage causers that are not guns', () => {
    expect(weaponName('ProjGrenade_C')).toBe('grenade')
    expect(weaponName('ProjC4_C')).toBe('C4')
    expect(weaponName('PanzerFaust100M_Projectile_C')).toBe('Panzerfaust')
    expect(weaponName('Bluezonebomb_EffectActor_C')).toBe('blue zone')
    expect(weaponName('BP_MolotovFireDebuff_C')).toBe('molotov')
    expect(weaponName('ProjMolotov_C')).toBe('molotov')
    expect(weaponName('BP_FireEffectController_C')).toBe('fire')
    expect(weaponName('JerrycanFire')).toBe('fire')
  })

  it('reads a player pawn as a punch, not as a weapon', () => {
    // The causer of a melee kill is the attacker's own pawn — and the bot
    // pawn is a different class again.
    expect(weaponName('PlayerMale_A_C')).toBe('fists')
    expect(weaponName('PlayerFemale_A_C')).toBe('fists')
    expect(weaponName('UltAIPawn_Base_Male_C')).toBe('fists')
    expect(weaponName('UltAIPawn_Base_Female_C')).toBe('fists')
  })

  it('reads a vehicle as a roadkill', () => {
    expect(weaponName('Uaz_B_01_C')).toBe('roadkill')
    expect(weaponName('Uaz_B_01_esports_C')).toBe('roadkill')
    expect(weaponName('Dacia_A_03_v2_Esports_C')).toBe('roadkill')
    expect(weaponName('BP_CoupeRB_C')).toBe('roadkill')
    expect(weaponName('Buggy_A_01_C')).toBe('roadkill')
  })

  it('does not let a vehicle prefix swallow a real weapon', () => {
    // The vehicle list is matched by prefix and is deliberately incomplete,
    // so the guard that keeps it safe is that every real weapon id carries
    // the `Weap`/`Item_Weapon_` prefix. Nothing here may become "roadkill".
    for (const id of ['WeapVector_C', 'WeapVSS_C', 'WeapUZI_C', 'WeapMini14_C',
      'WeapBerylM762_C', 'Item_Weapon_AWM_C']) {
      expect(weaponName(id), id).not.toBe('roadkill')
    }
  })

  it('names a thrown melee weapon after the weapon', () => {
    expect(weaponName('WeapMacheteProjectile_C')).toBe('Machete')
    expect(weaponName('WeapPanProjectile_C')).toBe('Pan')
  })

  it('leaves an unrecognised causer readable rather than mislabelling it', () => {
    // Every PUBG enum is open. A causer added next patch must fall through to
    // the tidied id, not to a wrong guess and not to an empty cell.
    expect(weaponName('ProjSomethingNew_C')).toBe('ProjSomethingNew')
    expect(weaponName('Hovercraft_X_99_C')).toBe('Hovercraft X 99')
  })
})

describe('distance', () => {
  it('switches to kilometres past 1000 m', () => {
    expect(distance(250)).toBe('250 m')
    expect(distance(999)).toBe('999 m')
    expect(distance(1500)).toBe('1.5 km')
  })

  it('renders absent as a dash but keeps a real zero', () => {
    expect(distance(null)).toBe('—')
    expect(distance(0)).toBe('0 m')
  })
})

describe('placement', () => {
  it('prefixes with a hash', () => {
    expect(placement(1)).toBe('#1')
    expect(placement(107)).toBe('#107')
  })
})

describe('itemName', () => {
  it('handles weapons like weaponName does', () => {
    expect(itemName('WeapHK416_C')).toBe('HK416')
    expect(itemName('Item_Weapon_AWM_C')).toBe('AWM')
    expect(itemName('Item_Weapon_Pan_C')).toBe('Pan')
  })

  it('reduces armour and packs to their tier', () => {
    // `Item_Head_F_01_Lv2_C` is "a level 2 helmet" — the model letter and
    // number mean nothing to a reader, and the slot label already says which
    // piece it is. These rendered in full as "Item Head F 01 Lv2".
    expect(itemName('Item_Head_F_01_Lv2_C')).toBe('Lv2')
    expect(itemName('Item_Armor_D_01_Lv2_C')).toBe('Lv2')
    expect(itemName('Item_Back_F_02_Lv3_C')).toBe('Lv3')
  })

  it('strips attachment decoration down to the part that identifies it', () => {
    expect(itemName('Item_Attach_Weapon_Muzzle_AR_MuzzleBrake_C')).toBe('AR Muzzle Brake')
    expect(itemName('Item_Attach_Weapon_Upper_CQBSS_C')).toBe('CQBSS')
    expect(itemName('Item_Attach_Weapon_Lower_AngledForeGrip_C')).toBe('Angled Fore Grip')
    expect(itemName('Item_Attach_Weapon_Stock_AR_Composite_C')).toBe('AR Composite')
  })

  it('names consumables and ammo', () => {
    expect(itemName('Item_Heal_FirstAid_C')).toBe('First Aid')
    expect(itemName('Item_Boost_EnergyDrink_C')).toBe('Energy Drink')
    expect(itemName('Item_Ammo_556mm_C')).toBe('556mm')
  })

  it('renders an unknown id rather than blanking the row', () => {
    // api-assets froze in Oct 2024 and ~11% of live ids are missing from it.
    expect(itemName('Item_Something_Brand_New_C')).toBe('Something Brand New')
    expect(itemName('totally-unknown')).toBe('totally-unknown')
    expect(itemName(null)).toBe('—')
    expect(itemName('')).toBe('—')
  })
})
