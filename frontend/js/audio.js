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

// 预加载音效
audioManager.load('card', 'assets/audio/discard.mp3');
audioManager.load('damage', 'assets/audio/damage.mp3');
audioManager.load('heal', 'assets/audio/recover.mp3');
audioManager.load('click', 'assets/audio/coin.mp3');
audioManager.load('die', 'assets/audio/die_male.mp3');
audioManager.load('win', 'assets/audio/win.mp3');
audioManager.load('lose', 'assets/audio/lose.mp3');
audioManager.load('judge', 'assets/audio/judge.mp3');
