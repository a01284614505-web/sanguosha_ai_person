/* Verify the opt-in TTS control and public-event allowlist without real audio output. */
'use strict';
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = (process.env.UI_BASE_URL || 'http://127.0.0.1:8888').replace(/\/$/, '');
(async () => {
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox'],
    ...(process.env.PLAYWRIGHT_EXECUTABLE_PATH ? {executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH} : {})});
  const page = await browser.newPage({viewport: {width: 390, height: 844}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.addInitScript(() => {
      window.__tts = {spoken: [], cancelled: 0, fail: false};
      Object.defineProperty(window, 'SpeechSynthesisUtterance', {configurable: true, value: function (text) { this.text = text; this.lang = ''; this.voice = null; }});
      Object.defineProperty(window, 'speechSynthesis', {configurable: true, value: {
        getVoices: () => [{name: '测试普通话', lang: 'zh-CN'}],
        cancel: () => { window.__tts.cancelled++; },
        speak: utterance => {
          if (window.__tts.fail) throw new Error('synthetic speech error');
          window.__tts.spoken.push({text: utterance.text, lang: utterance.lang, voice: utterance.voice && utterance.voice.name});
        }
      }});
      localStorage.setItem('globalSettings', JSON.stringify({speech_enabled: false}));
      sessionStorage.setItem('profileId', JSON.stringify('tts_browser_profile'));
      sessionStorage.setItem('gameConfig', JSON.stringify({selected_hero: {id: 'caocao', name: '曹操', faction: '魏', skills: []},
        ais: [1, 2, 3, 4].map(i => ({name: 'AI' + i})), player_name: '语音验收'}));
    });
    await page.routeWebSocket('ws://127.0.0.1:8889', ws => {
      ws.onMessage(raw => {
        const msg = JSON.parse(raw.toString());
        if (msg.type === 'create_game') ws.send(JSON.stringify({type: 'game_created', game_id: 'tts-browser-check', profile_id: 'tts_browser_profile'}));
      });
    });
    await page.goto(base + '/game.html');
    await page.waitForFunction(() => !!window.GameUI);
    await page.waitForTimeout(200);
    await page.locator('#sbtn').click();
    await page.locator('#gsSpeech').waitFor();
    const modalWidth = await page.evaluate(() => ({body: document.documentElement.scrollWidth, viewport: innerWidth}));
    if (modalWidth.body > modalWidth.viewport + 1) throw new Error('speech setting caused mobile overflow: ' + JSON.stringify(modalWidth));
    if (await page.locator('#gsSpeech').isChecked()) throw new Error('speech must be off by default');
    const disabledResult = await page.evaluate(() => window.SpeechAnnouncer.speakPublicEvent({event_kind: 'skill_activation', message: '默认关闭'}));
    if (disabledResult !== false || (await page.evaluate(() => window.__tts.spoken.length)) !== 0) throw new Error('speech was active while disabled');
    await page.locator('#gsSpeech').check();
    await page.locator('#gsSave').click();
    const setting = await page.evaluate(() => JSON.parse(localStorage.getItem('globalSettings') || '{}').speech_enabled);
    if (setting !== true) throw new Error('speech setting was not saved');

    const integration = await page.evaluate(() => {
      let called = 0;
      const original = window.SpeechAnnouncer.speakPublicEvent;
      window.SpeechAnnouncer.speakPublicEvent = event => { called++; return original(event); };
      window.gameClient.onEventNotification({event_kind: 'skill_activation', actor_id: null, message: '许褚发动【裸衣】'});
      window.SpeechAnnouncer.speakPublicEvent = original;
      return {called, spoken: window.__tts.spoken.length};
    });
    if (integration.called !== 1) throw new Error('public event handler did not invoke speech announcer: ' + JSON.stringify(integration));
    const announced = await page.waitForFunction(() => window.__tts.spoken.length === 1, null, {timeout: 3000}).then(() => true).catch(() => false);
    if (!announced) throw new Error('public event did not reach speech engine: ' + JSON.stringify(await page.evaluate(() => ({
      speech: window.__tts, enabled: window.getGlobalSettings().speech_enabled,
      supported: window.SpeechAnnouncer && window.SpeechAnnouncer.isSupported(),
      globals: {client: !!window.gameClient, announce: !!window.SpeechAnnouncer}
    }))));
    let spoken = await page.evaluate(() => window.__tts.spoken.slice());
    if (spoken[0].lang !== 'zh-CN' || spoken[0].voice !== '测试普通话') throw new Error('Chinese device voice was not selected: ' + JSON.stringify(spoken));

    const phaseSpoken = await page.evaluate(() => window.SpeechAnnouncer.speakPublicEvent({event_kind: 'phase', player_name: '曹操', phase: 'draw'}));
    if (!phaseSpoken || (await page.evaluate(() => window.__tts.spoken[1]?.text)) !== '曹操进入摸牌阶段') throw new Error('public phase fallback was not narrated');
    const ignored = await page.evaluate(() => [
      window.SpeechAnnouncer.speakPublicEvent({event_kind: 'chat', message: '聊天内容不进入播报'}),
      window.SpeechAnnouncer.speakPublicEvent({event_kind: 'decision_trace', message: 'AI 思考内容不进入播报'}),
      window.SpeechAnnouncer.speakPublicEvent({event_kind: 'private_card', message: '不公开的手牌内容'})
    ]);
    if (ignored.some(Boolean)) throw new Error('non-public event class was accepted');
    if ((await page.evaluate(() => window.__tts.spoken.length)) !== 2) throw new Error('non-allowlisted event was spoken');

    await page.locator('#sbtn').click();
    await page.locator('#gsSpeech').uncheck();
    await page.locator('#gsSave').click();
    const cancelAfterDisable = await page.evaluate(() => window.__tts.cancelled);
    await page.evaluate(() => window.SpeechAnnouncer.speakPublicEvent({event_kind: 'draw', message: '曹操摸了两张牌'}));
    if ((await page.evaluate(() => window.__tts.spoken.length)) !== 2) throw new Error('speech continued after it was disabled');

    await page.locator('#sbtn').click();
    await page.locator('#gsSpeech').check();
    await page.locator('#gsSave').click();
    await page.evaluate(() => { window.__tts.fail = true; });
    const failedSpeech = await page.evaluate(() => window.SpeechAnnouncer.speakPublicEvent({event_kind: 'skill_activation', message: '技能播报失败后牌局仍继续'}));
    if (failedSpeech !== false) throw new Error('speech engine error was not suppressed');
    await page.evaluate(() => window.gameClient.onEventNotification({event_kind: 'skill_activation', actor_id: null, message: '技能播报失败后牌局仍继续'}));
    if (!(await page.locator('#log').innerText()).includes('技能播报失败后牌局仍继续')) throw new Error('speech failure interrupted normal event handling');
    if (errors.length) throw new Error('page errors: ' + JSON.stringify(errors));
    console.log(JSON.stringify({check: 'TTS_BROWSER_OK', viewport: '390x844', default_off: true, public_skill_event_spoken: true, public_phase_spoken: true,
      non_allowlisted_events_ignored: true, disable_stops_and_blocks_speech: cancelAfterDisable > 0,
      speech_failure_keeps_event_flow: true, voice: spoken[0].voice, page_errors: errors}, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
