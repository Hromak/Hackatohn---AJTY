import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseCommand, wordsToNumbers } from '../js/voice.js';

const ctx = { names: { home: ['Draci'], away: ['Vlci'] } };

test('the example from the brief', () => {
  assert.deepEqual(parseCommand('domácí gól 90 asistence 98 čas 5:38', ctx),
    { team: 'home', result: 'goal', shooter: 90, assist: 98, noAssist: false, time: '05:38', strength: null });
});

test('away shot wide, no time', () => {
  const c = parseCommand('hosté střela mimo 17', ctx);
  assert.equal(c.team, 'away');
  assert.equal(c.result, 'miss');
  assert.equal(c.shooter, 17);
  assert.equal(c.time, null);
});

test('numbers said in words, without diacritics, in any order', () => {
  const c = parseCommand('gol devadesat asistence devadesat osm cas pet tricet osm domaci', ctx);
  assert.equal(c.shooter, 90);
  assert.equal(c.assist, 98);
  assert.equal(c.time, '05:38');
  assert.equal(c.team, 'home');
});

test('wordsToNumbers handles compounds and the "jednadevadesát" form', () => {
  assert.equal(wordsToNumbers('dvacet tři'), '23');
  assert.equal(wordsToNumbers('jednadevadesát'), '91');
  assert.equal(wordsToNumbers('sedmnáct'), '17');
  assert.equal(wordsToNumbers('nula'), '0');
});

test('team by short name and declension; results by variant words', () => {
  assert.equal(parseCommand('Vlci tyčka 9', ctx).team, 'away');
  assert.equal(parseCommand('domácích tyčku 9', ctx).result, 'post');
  assert.equal(parseCommand('hostů chytil brankář 9', ctx).result, 'on_goal');
  assert.equal(parseCommand('střela na bránu 9', ctx).result, 'on_goal');
  assert.equal(parseCommand('střela 9', ctx).result, null);
});

test('strength, "bez asistence" and time in other shapes', () => {
  const c = parseCommand('přesilovka domácí gól 13 bez asistence čas 12 05', ctx);
  assert.equal(c.strength, 'power_play');
  assert.equal(c.noAssist, true);
  assert.equal(c.assist, null);
  assert.equal(c.time, '12:05');
  assert.equal(parseCommand('oslabení hosté mimo 4 v čase 7.09', ctx).time, '07:09');
  assert.equal(parseCommand('oslabení hosté mimo 4', ctx).strength, 'short_handed');
});

test('time words "minuta" and "sekund"', () => {
  assert.equal(parseCommand('gól 9 čas 5 minut 8 sekund', ctx).time, '05:08');
});
