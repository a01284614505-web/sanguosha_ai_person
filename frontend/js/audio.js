// 音效管理器
class AudioManager {
    constructor() {
        this.sounds = {};
        this.bgm = null;
        this.enabled = localStorage.getItem('audioEnabled') !== 'false';
        this.bgmEnabled = localStorage.getItem('bgmEnabled') !== 'false';
        this.volume = parseFloat(localStorage.getItem('audioVolume') || '0.5');
        this.bgmVolume = parseFloat(localStorage.getItem('bgmVolume') || '0.3');
    }
    
    load(name, url) {
        const audio = new Audio(url);
        audio.volume = this.volume;
        this.sounds[name] = audio;
    }
    
    play(name) {
        if (!this.enabled) return;
        const gs = window.getGlobalSettings ? window.getGlobalSettings() : {};
        if (gs.sfx_enabled === false) return;
        const sound = this.sounds[name];
        if (sound) {
            const vol = Number(gs.sfx_volume);
            sound.volume = Number.isFinite(vol) ? Math.max(0, Math.min(1, vol)) : this.volume;
            sound.currentTime = 0;
            sound.play().catch(e => {});
        }
    }
    
    playBGM(url) {
        if (!this.bgmEnabled) return;
        if (this.bgm) this.bgm.pause();
        this.bgm = new Audio(url);
        this.bgm.volume = this.bgmVolume;
        this.bgm.loop = true;
        this.bgm.play().catch(e => {});
    }
    
    stopBGM() {
        if (this.bgm) {
            this.bgm.pause();
            this.bgm = null;
        }
    }
    
    setEnabled(enabled) {
        this.enabled = enabled;
        localStorage.setItem('audioEnabled', enabled);
    }
    
    setBGMEnabled(enabled) {
        this.bgmEnabled = enabled;
        localStorage.setItem('bgmEnabled', enabled);
        if (!enabled && this.bgm) this.stopBGM();
    }
    
    setVolume(vol) {
        this.volume = Math.max(0, Math.min(1, vol));
        localStorage.setItem('audioVolume', this.volume);
        Object.values(this.sounds).forEach(s => s.volume = this.volume);
    }
    
    setBGMVolume(vol) {
        this.bgmVolume = Math.max(0, Math.min(1, vol));
        localStorage.setItem('bgmVolume', this.bgmVolume);
        if (this.bgm) this.bgm.volume = this.bgmVolume;
    }
}

const audioManager = new AudioManager();
if (typeof window !== 'undefined') {
    window.audioManager = audioManager;
}

// Optional, device-local narration of explicitly public game events. This never
// receives chat, prompts, private cards, AI thoughts, or decision traces.
(function (global) {
    'use strict';
    const PUBLIC_EVENT_KINDS = new Set([
        'card_to_discard', 'judge', 'draw', 'phase', 'skill_activation', 'skill_decision', 'dying_rescue'
    ]);
    const PHASE_NAMES = {prepare: '准备阶段', judge: '判定阶段', draw: '摸牌阶段', play: '出牌阶段', discard: '弃牌阶段', end: '结束阶段'};

    function enabled() {
        try {
            const settings = global.getGlobalSettings ? global.getGlobalSettings() :
                JSON.parse(localStorage.getItem('globalSettings') || '{}');
            return settings.speech_enabled === true;
        } catch (_) { return false; }
    }

    function stop() {
        try {
            if (global.speechSynthesis && typeof global.speechSynthesis.cancel === 'function') global.speechSynthesis.cancel();
        } catch (_) { /* Speech is an optional enhancement. */ }
    }

    function speakPublicEvent(event) {
        if (!enabled() || !event || !PUBLIC_EVENT_KINDS.has(event.event_kind)) return false;
        let sourceText = event.message || '';
        if (!sourceText && event.event_kind === 'phase') {
            const phase = PHASE_NAMES[event.phase];
            if (phase && event.player_name) sourceText = event.player_name + (event.skipped ? '跳过' : '进入') + phase;
        }
        const text = String(sourceText).replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 180);
        if (!text) return false;
        try {
            const speech = global.speechSynthesis;
            const Utterance = global.SpeechSynthesisUtterance;
            if (!speech || typeof speech.speak !== 'function' || typeof Utterance !== 'function') return false;
            // Drop stale narration instead of building a queue that could lag behind play.
            speech.cancel();
            const utterance = new Utterance(text);
            utterance.lang = 'zh-CN';
            const voices = typeof speech.getVoices === 'function' ? speech.getVoices() : [];
            const chineseVoice = voices.find(voice => /^zh(?:-|$)/i.test(voice.lang || ''));
            if (chineseVoice) utterance.voice = chineseVoice;
            utterance.onerror = () => {};
            speech.speak(utterance);
            return true;
        } catch (_) { return false; }
    }

    global.SpeechAnnouncer = { speakPublicEvent, stop, isSupported: () =>
        !!(global.speechSynthesis && typeof global.SpeechSynthesisUtterance === 'function') };
    global.addEventListener('global-settings-changed', event => {
        if (!event.detail || event.detail.speech_enabled !== true) stop();
    });
})(typeof window !== 'undefined' ? window : globalThis);

// 预加载音效
audioManager.load('card', 'assets/audio/discard.mp3');
audioManager.load('damage', 'assets/audio/damage.mp3');
audioManager.load('heal', 'assets/audio/recover.mp3');
audioManager.load('click', 'assets/audio/coin.mp3');
audioManager.load('die', 'assets/audio/die_male.mp3');
audioManager.load('win', 'assets/audio/win.mp3');
audioManager.load('lose', 'assets/audio/lose.mp3');
audioManager.load('judge', 'assets/audio/judge.mp3');
