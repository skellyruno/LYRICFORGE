/* SkellyMotion "Make" overlay: music videos, animations, livestream scenes, before/after and visualizers.
 * One data-driven form per tab (TABS below). Every upload goes out as multipart form data, the job is polled through the
 * shared helpers that static/autoclip.js exposes as window.SkellyUI, and every result is shown with textContent only. */
(() => {
'use strict';
const $ = (id) => document.getElementById(id);
const ui = () => window.SkellyUI;
const toast = (m, e) => { if (ui()) ui().toast(m, e); };

const ASPECT = { name: 'aspect', label: 'Shape', type: 'select', value: 'landscape',
  options: [['landscape', 'Landscape 16:9 (YouTube)'], ['portrait', 'Vertical 9:16 (Shorts, TikTok)'], ['square', 'Square 1:1']] };
const RES = { name: 'resolution', label: 'Size', type: 'select', value: '1080p', options: [['1080p', '1080p'], ['720p', '720p (faster)']] };
const WATERMARK = { name: 'watermark', label: 'Add my logo watermark', type: 'check', value: true };
const ENDCARD = { name: 'endcard', label: 'Add my end card', type: 'check', value: false };
const AUDIO_ACCEPT = 'audio/*,video/*,.mp3,.wav,.m4a,.aac,.flac,.ogg,.opus,.mp4,.mov,.mkv,.webm,.m4v';
const IMG_ACCEPT = 'image/png,image/jpeg,.png,.jpg,.jpeg';
const VIDEO_ACCEPT = 'video/*,.mp4,.mov,.mkv,.webm,.m4v';

const TABS = [
  { id: 'mv', title: 'Music video', endpoint: '/api/music-video', go: 'Make the music video',
    blurb: 'Pick a song and some footage. Every cut lands on the beat, faster in loud sections, with a flash at each drop. Works best with a steady tempo.',
    fields: [
      { name: 'song', label: 'Song', type: 'file', accept: AUDIO_ACCEPT, required: true, wide: true },
      { name: 'clips', label: 'Footage (1 to 12 video clips)', type: 'file', accept: VIDEO_ACCEPT, multiple: true, required: true, wide: true },
      { name: 'intensity', label: 'Cut speed', type: 'select', value: 'medium', options: [['calm', 'Calm (every 4 to 8 beats)'], ['medium', 'Medium'], ['hype', 'Hype (every 1 to 2 beats)']] },
      ASPECT, RES,
      { name: 'title', label: 'Song title (optional)', type: 'text', max: 70 }, { name: 'artist', label: 'Artist (optional)', type: 'text', max: 60 },
      WATERMARK, ENDCARD] },
  { id: 'anim', title: 'Animations', endpoint: '/api/animation', go: 'Make the animation',
    blurb: 'Animated text or a countdown on your brand colors, with generated sound effects. Great for intros, stingers and Shorts openers.',
    fields: [
      { name: 'template', label: 'Template', type: 'select', value: 'kinetic', options: [['kinetic', 'Animated text'], ['countdown', 'Countdown']] },
      { name: 'style', label: 'Text style', type: 'select', value: 'pop', showIf: { template: 'kinetic' },
        options: [['pop', 'Pop'], ['slide', 'Slide up'], ['typewriter', 'Typewriter']] },
      { name: 'count', label: 'Count from', type: 'number', min: 3, max: 10, value: 5, showIf: { template: 'countdown' } },
      { name: 'text', label: 'Text (one slide per line, up to 12)', type: 'textarea', wide: true, showIf: { template: 'kinetic' },
        hint: 'Put *asterisks* around a word to highlight it in your accent color.', value: 'Meet *SkellyTune*\nShape your tone' },
      ASPECT, RES, { name: 'sfx', label: 'Add sound effects', type: 'check', value: true }] },
  { id: 'stream', title: 'Livestream pack', endpoint: '/api/livestream', go: 'Make the scenes',
    blurb: 'A 3D-style intro stinger plus looping Starting Soon, Be Right Back and Ending scenes built from your logo and brand colors. The loops repeat seamlessly in OBS.',
    fields: [
      { name: 'title', label: 'Channel or show name', type: 'text', max: 40 }, { name: 'subtitle', label: 'Tagline', type: 'text', max: 60 },
      { name: 'scenes', label: 'Scenes to make', type: 'checks', wide: true, value: ['intro', 'starting', 'brb', 'ending'],
        options: [['intro', 'Intro (5 s, with sound)'], ['starting', 'Starting soon (loop)'], ['brb', 'Be right back (loop)'], ['ending', 'Ending (loop)']] },
      { name: 'resolution', label: 'Size', type: 'select', value: '1080p', options: [['1080p', '1080p'], ['720p', '720p (faster)']] }] },
  { id: 'ab', title: 'Before / After', endpoint: '/api/ab', go: 'Make the comparison',
    blurb: 'Show what your plugin does: the same moment, alternating between before and after, loudness-matched so the difference you hear is tone, not volume.',
    fields: [
      { name: 'before', label: 'Before (audio or screen recording)', type: 'file', accept: AUDIO_ACCEPT, required: true },
      { name: 'after', label: 'After', type: 'file', accept: AUDIO_ACCEPT, required: true },
      { name: 'mode', label: 'Pattern', type: 'select', value: 'repeat', options: [['repeat', 'Before then after, repeated'], ['toggle', 'Quick toggling']] },
      { name: 'step', label: 'Seconds per side (2 to 10)', type: 'number', min: 2, max: 10, value: 4 },
      { name: 'rounds', label: 'Rounds (1 to 4)', type: 'number', min: 1, max: 4, value: 2 },
      { name: 'start', label: 'Start at second (blank = best moment)', type: 'text', max: 8 },
      { name: 'label_before', label: 'Label for before', type: 'text', max: 20, value: 'BEFORE' }, { name: 'label_after', label: 'Label for after', type: 'text', max: 20, value: 'AFTER' },
      { name: 'title', label: 'Title (optional)', type: 'text', max: 70, wide: true },
      { name: 'match_loudness', label: 'Match loudness (fair comparison)', type: 'check', value: true },
      ASPECT, RES, WATERMARK, ENDCARD] },
  { id: 'viz', title: 'Visualizer', endpoint: '/api/visualizer', go: 'Make the visualizer',
    blurb: 'An audio-reactive bars or waveform video for any track. For lyrics over a visualizer, use the Auto panel in the editor.',
    fields: [
      { name: 'audio_file', label: 'Audio', type: 'file', accept: AUDIO_ACCEPT, required: true, wide: true },
      { name: 'style', label: 'Style', type: 'select', value: 'bars', options: [['bars', 'Bars'], ['wave', 'Waveform'], ['both', 'Bars and waveform']] },
      ASPECT, RES, { name: 'title', label: 'Title (optional)', type: 'text', max: 70 }, { name: 'artist', label: 'Artist (optional)', type: 'text', max: 60 }, WATERMARK] },
  { id: 'gif', title: 'GIF', endpoint: '/api/gif', go: 'Make the GIF',
    blurb: 'Turn any moment of a video into a looping GIF for a README, a forum post or a chat. It is shrunk automatically to stay under 12 MB, so keep it short.',
    fields: [
      { name: 'file', label: 'Video', type: 'file', accept: VIDEO_ACCEPT, required: true, wide: true },
      { name: 'start', label: 'Start at second', type: 'number', min: 0, max: 100000, value: 0 },
      { name: 'seconds', label: 'Length in seconds (1 to 12)', type: 'number', min: 1, max: 12, value: 5 },
      { name: 'width', label: 'Width', type: 'select', value: '480', options: [['320', '320 px (small)'], ['480', '480 px'], ['640', '640 px'], ['800', '800 px'], ['960', '960 px (large)']] },
      { name: 'fps', label: 'Smoothness', type: 'select', value: '12', options: [['8', '8 frames/s (smallest)'], ['12', '12 frames/s'], ['15', '15 frames/s'], ['20', '20 frames/s (smoothest)']] }] },
  { id: 'enhance', title: 'Audio enhance', endpoint: '/api/enhance', go: 'Clean up the audio',
    blurb: 'Reduce hum and background noise and set a loudness target on any recording. A video keeps its picture untouched; audio comes back as an .m4a. Always listen before you publish: strong cleanup can sound thin.',
    fields: [
      { name: 'file', label: 'Audio or video', type: 'file', accept: AUDIO_ACCEPT, required: true, wide: true },
      { name: 'level', label: 'Voice cleanup', type: 'select', value: 'medium', options: [['off', 'Off'], ['light', 'Light'], ['medium', 'Medium'], ['strong', 'Strong']] },
      { name: 'loudness', label: 'Loudness target', type: 'select', value: '-14', options: [['-14', 'YouTube and streaming (-14 LUFS)'], ['-16', 'Podcast (-16 LUFS)'], ['-23', 'Broadcast (-23 LUFS)'], ['0', 'Leave the volume alone']] }] },
  { id: 'lower', title: 'Lower third', endpoint: '/api/lower-third', go: 'Add the lower third',
    blurb: 'Show a name and title in your brand colors at the bottom of a video. The video is re-encoded, so this takes about as long as the video itself.',
    fields: [
      { name: 'file', label: 'Video', type: 'file', accept: VIDEO_ACCEPT, required: true, wide: true },
      { name: 'name', label: 'Name', type: 'text', max: 40, required: true }, { name: 'role', label: 'Title or role (optional)', type: 'text', max: 60 },
      { name: 'start', label: 'Show at second', type: 'number', min: 0, max: 100000, value: 1 },
      { name: 'duration', label: 'Show for (seconds)', type: 'number', min: 2, max: 15, value: 5 },
      { name: 'every', label: 'Repeat', type: 'select', value: '0', options: [['0', 'Just once'], ['60', 'Every minute'], ['120', 'Every 2 minutes'], ['300', 'Every 5 minutes']] }] },
  { id: 'speed', title: 'Speed', endpoint: '/api/speed', go: 'Change the speed',
    blurb: 'Speed a video up or slow it down (0.25x to 4x). The voice keeps its pitch. Great for turning a long setup into a quick time-lapse.',
    fields: [
      { name: 'file', label: 'Video', type: 'file', accept: VIDEO_ACCEPT, required: true, wide: true },
      { name: 'factor', label: 'Speed', type: 'select', value: '2', options: [['0.25', '0.25x (very slow)'], ['0.5', '0.5x (slow)'], ['1.5', '1.5x'], ['2', '2x'], ['3', '3x'], ['4', '4x (time-lapse)']] }] },
  { id: 'trim', title: 'Trim', endpoint: '/api/trim', go: 'Cut the video',
    blurb: 'Keep just one part of a video. The cut is frame-accurate, so the picture starts exactly where you say. Leave End at 0 to keep everything after the start.',
    fields: [
      { name: 'file', label: 'Video', type: 'file', accept: VIDEO_ACCEPT, required: true, wide: true },
      { name: 'start', label: 'Start at second', type: 'number', min: 0, max: 100000, value: 0 },
      { name: 'end', label: 'End at second (0 = the end)', type: 'number', min: 0, max: 100000, value: 0 }] },
  { id: 'shrink', title: 'Shrink to size', endpoint: '/api/shrink', go: 'Shrink the video',
    blurb: 'Make a video small enough to send or upload. The picture gets smaller and softer to fit the size you pick; a long video needs a bigger size.',
    fields: [
      { name: 'file', label: 'Video', type: 'file', accept: VIDEO_ACCEPT, required: true, wide: true },
      { name: 'size', label: 'Fit under', type: 'select', value: '25', options: [['8', '8 MB'], ['25', '25 MB (Discord)'], ['50', '50 MB'], ['100', '100 MB']] }] },
  { id: 'sheet', title: 'Contact sheet', endpoint: '/api/contact-sheet', go: 'Make the contact sheet',
    blurb: 'One picture with frames from the whole video and their times: a quick storyboard for planning chapters or showing what a video contains.',
    fields: [
      { name: 'file', label: 'Video', type: 'file', accept: VIDEO_ACCEPT, required: true, wide: true },
      { name: 'title', label: 'Title (optional)', type: 'text', max: 60 },
      { name: 'cols', label: 'Columns', type: 'select', value: '3', options: [['2', '2'], ['3', '3'], ['4', '4'], ['5', '5']] },
      { name: 'rows', label: 'Rows', type: 'select', value: '3', options: [['2', '2'], ['3', '3'], ['4', '4'], ['5', '5']] }] },
  { id: 'quote', title: 'Quote card', endpoint: '/api/quote-card', go: 'Make the card',
    blurb: 'A shareable picture of a tip or quote in your brand colors and font. Long text gets smaller to fit.',
    fields: [
      { name: 'quote', label: 'Quote or tip', type: 'textarea', max: 280, wide: true, required: true },
      { name: 'author', label: 'Name or source (optional)', type: 'text', max: 60 },
      { name: 'aspect', label: 'Shape', type: 'select', value: 'square', options: [['square', 'Square 1:1'], ['portrait', 'Portrait 4:5'], ['landscape', 'Landscape 16:9']] }] },
  { id: 'fade', title: 'Fades', endpoint: '/api/fade', go: 'Add the fades',
    blurb: 'Fade a video in from black and out to black, with the sound fading too. Set one of them to 0 to fade only the start or the end.',
    fields: [
      { name: 'file', label: 'Video', type: 'file', accept: VIDEO_ACCEPT, required: true, wide: true },
      { name: 'fade_in', label: 'Fade in (seconds, 0 to 5)', type: 'number', min: 0, max: 5, value: 1 },
      { name: 'fade_out', label: 'Fade out (seconds, 0 to 5)', type: 'number', min: 0, max: 5, value: 1 }] },
  { id: 'loop', title: 'Loop', endpoint: '/api/loop', go: 'Loop the video',
    blurb: 'Repeat a short video 2 to 10 times as one file (up to an hour in all), for a background loop or a longer clip.',
    fields: [
      { name: 'file', label: 'Video', type: 'file', accept: VIDEO_ACCEPT, required: true, wide: true },
      { name: 'times', label: 'Play it', type: 'select', value: '3', options: [['2', '2 times'], ['3', '3 times'], ['5', '5 times'], ['10', '10 times']] }] },
  { id: 'extract', title: 'Extract audio', endpoint: '/api/extract-audio', go: 'Extract the audio',
    blurb: 'Pull the sound out of a video as an .m4a file, without touching the original.',
    fields: [{ name: 'file', label: 'Video or audio', type: 'file', accept: AUDIO_ACCEPT, required: true, wide: true }] },
  { id: 'frame', title: 'Still frame', endpoint: '/api/frame', go: 'Grab the frame',
    blurb: 'Save one full-quality picture from a video, for a thumbnail, a cover or a bug report.',
    fields: [
      { name: 'file', label: 'Video', type: 'file', accept: VIDEO_ACCEPT, required: true, wide: true },
      { name: 'at', label: 'At second', type: 'number', min: 0, max: 100000, value: 0 }] },
  { id: 'swap', title: 'Swap audio', endpoint: '/api/swap-audio', go: 'Replace the audio',
    blurb: 'Replace a video\'s sound with another track. The result is as long as the video: a longer track is cut off, a shorter one ends early. The picture is not re-encoded when it can be copied.',
    fields: [
      { name: 'file', label: 'Video', type: 'file', accept: VIDEO_ACCEPT, required: true, wide: true },
      { name: 'audio', label: 'New audio track', type: 'file', accept: 'audio/*,.mp3,.wav,.m4a,.aac,.flac,.ogg,.opus', required: true, wide: true }] },
  { id: 'mute', title: 'Remove audio', endpoint: '/api/quick/mute', go: 'Remove the audio',
    blurb: 'Strip the sound from a video. The picture is copied untouched, so this is nearly instant.',
    fields: [
      { name: 'video', label: 'Video', type: 'file', accept: VIDEO_ACCEPT, required: true, wide: true }] },
  { id: 'rotate', title: 'Rotate / flip', endpoint: '/api/quick/rotate', go: 'Turn the video',
    blurb: 'Turn a video a quarter turn, upside down, or mirror it. Useful for a phone clip that came out sideways.',
    fields: [
      { name: 'video', label: 'Video', type: 'file', accept: VIDEO_ACCEPT, required: true, wide: true },
      { name: 'mode', label: 'What to do', type: 'select', value: 'cw', options: [['cw', 'Rotate right (clockwise)'], ['ccw', 'Rotate left'], ['180', 'Turn upside down'], ['hflip', 'Mirror left to right'], ['vflip', 'Flip top to bottom']] }] },
  { id: 'resize', title: 'Resize', endpoint: '/api/quick/resize', go: 'Resize the video',
    blurb: 'Make a video smaller (never larger) so it uploads faster or fits a limit. The shape is kept.',
    fields: [
      { name: 'video', label: 'Video', type: 'file', accept: VIDEO_ACCEPT, required: true, wide: true },
      { name: 'height', label: 'New height', type: 'select', value: '720', options: [['360', '360 p'], ['480', '480 p'], ['720', '720 p'], ['1080', '1080 p'], ['1440', '1440 p']] }] },
  { id: 'fps', title: 'Frame rate', endpoint: '/api/quick/fps', go: 'Change the frame rate',
    blurb: 'Change how many frames per second a video has, for example to match another clip before editing them together.',
    fields: [
      { name: 'video', label: 'Video', type: 'file', accept: VIDEO_ACCEPT, required: true, wide: true },
      { name: 'fps', label: 'Frames per second', type: 'select', value: '30', options: [['24', '24 (film)'], ['25', '25'], ['30', '30'], ['50', '50'], ['60', '60 (smooth)']] }] },
  { id: 'reverse', title: 'Reverse', endpoint: '/api/quick/reverse', go: 'Reverse the video',
    blurb: 'Play a short video backwards, picture and sound. Limited to 20 seconds (it holds every frame in memory) and shrunk to 720 p if larger.',
    fields: [
      { name: 'video', label: 'Video', type: 'file', accept: VIDEO_ACCEPT, required: true, wide: true }] },
  { id: 'volume', title: 'Volume', endpoint: '/api/quick/volume', go: 'Change the volume',
    blurb: 'Make the whole video quieter or louder. Boosts are limited so loud peaks do not distort.',
    fields: [
      { name: 'video', label: 'Video', type: 'file', accept: VIDEO_ACCEPT, required: true, wide: true },
      { name: 'db', label: 'Change by', type: 'select', value: '6', options: [['-20', '-20 dB (much quieter)'], ['-12', '-12 dB'], ['-6', '-6 dB'], ['6', '+6 dB'], ['12', '+12 dB'], ['20', '+20 dB (much louder)']] }] },
  { id: 'watermark', title: 'Watermark', endpoint: '/api/quick/watermark', go: 'Add the watermark',
    blurb: 'Put a logo in a corner of a video. Leave the logo empty to use the one saved in your Brand kit.',
    fields: [
      { name: 'video', label: 'Video', type: 'file', accept: VIDEO_ACCEPT, required: true, wide: true },
      { name: 'logo', label: 'Logo (optional, PNG or JPG)', type: 'file', accept: 'image/png,image/jpeg,.png,.jpg,.jpeg', wide: true },
      { name: 'corner', label: 'Where', type: 'select', value: 'br', options: [['br', 'Bottom right'], ['bl', 'Bottom left'], ['tr', 'Top right'], ['tl', 'Top left'], ['center', 'Center']] },
      { name: 'size', label: 'Logo size (% of the width)', type: 'number', min: 5, max: 50, value: 15 },
      { name: 'opacity', label: 'Opacity (%)', type: 'number', min: 20, max: 100, value: 80 }] },
  { id: 'crop', title: 'Crop to shape', endpoint: '/api/quick/crop', go: 'Crop the video',
    blurb: 'Cut a video to a square, 4:5, vertical or wide shape by trimming the edges from the middle. Nothing is stretched.',
    fields: [
      { name: 'video', label: 'Video', type: 'file', accept: VIDEO_ACCEPT, required: true, wide: true },
      { name: 'shape', label: 'Shape', type: 'select', value: '1:1', options: [['1:1', 'Square 1:1'], ['4:5', 'Portrait 4:5'], ['9:16', 'Vertical 9:16'], ['16:9', 'Wide 16:9']] }] },
  { id: 'grade', title: 'Color', endpoint: '/api/quick/grade', go: 'Adjust the color',
    blurb: 'Brighten, add contrast or change how colorful a video is. Move at least one slider; the sliders go from -50 to 50.',
    fields: [
      { name: 'video', label: 'Video', type: 'file', accept: VIDEO_ACCEPT, required: true, wide: true },
      { name: 'brightness', label: 'Brightness', type: 'number', min: -50, max: 50, value: 0 },
      { name: 'contrast', label: 'Contrast', type: 'number', min: -50, max: 50, value: 0 },
      { name: 'saturation', label: 'Color (-50 is black and white)', type: 'number', min: -50, max: 50, value: 0 }] },
  { id: 'cleanup', title: 'Clean up picture', endpoint: '/api/quick/cleanup', go: 'Clean up the picture',
    blurb: 'Reduce grain and noise, and sharpen a soft picture. Strong settings can make a picture look waxy, so start light.',
    fields: [
      { name: 'video', label: 'Video', type: 'file', accept: VIDEO_ACCEPT, required: true, wide: true },
      { name: 'denoise', label: 'Remove grain', type: 'select', value: 'light', options: [['off', 'Off'], ['light', 'Light'], ['medium', 'Medium'], ['strong', 'Strong']] },
      { name: 'sharpen', label: 'Sharpen', type: 'select', value: 'off', options: [['off', 'Off'], ['light', 'Light'], ['medium', 'Medium'], ['strong', 'Strong']] }] },
  { id: 'waveform', title: 'Waveform picture', endpoint: '/api/quick/waveform', go: 'Draw the waveform',
    blurb: 'Draw the shape of a sound as a picture in your accent color, for a thumbnail, a post or a podcast cover.',
    fields: [
      { name: 'audio', label: 'Audio or video', type: 'file', accept: AUDIO_ACCEPT, required: true, wide: true },
      { name: 'shape', label: 'Shape', type: 'select', value: 'wide', options: [['wide', 'Wide 1600 x 400'], ['banner', 'Banner 1600 x 200'], ['square', 'Square 1000 x 1000']] }] },
  { id: 'still', title: 'Image + audio', endpoint: '/api/quick/still', go: 'Make the video',
    blurb: 'Turn a cover picture and a song into a video, ready for YouTube. The picture can slowly push in.',
    fields: [
      { name: 'image', label: 'Picture (PNG or JPG)', type: 'file', accept: 'image/png,image/jpeg,.png,.jpg,.jpeg', required: true, wide: true },
      { name: 'audio', label: 'Song or audio', type: 'file', accept: AUDIO_ACCEPT, required: true, wide: true },
      { name: 'shape', label: 'Shape', type: 'select', value: 'landscape', options: [['landscape', 'Wide 16:9'], ['portrait', 'Vertical 9:16'], ['square', 'Square 1:1']] },
      { name: 'zoom', label: 'Movement', type: 'select', value: 'slow', options: [['slow', 'Slow push-in'], ['none', 'Still picture']] }] },
  { id: 'music', title: 'Background music', endpoint: '/api/quick/music', go: 'Add the music',
    blurb: 'Lay a music track under a video. The music loops to fit, and with ducking it gets quieter whenever someone talks.',
    fields: [
      { name: 'video', label: 'Video', type: 'file', accept: VIDEO_ACCEPT, required: true, wide: true },
      { name: 'music', label: 'Music', type: 'file', accept: AUDIO_ACCEPT, required: true, wide: true },
      { name: 'db', label: 'Music level', type: 'select', value: '-18', options: [['-30', 'Very quiet'], ['-24', 'Quiet'], ['-18', 'Under speech'], ['-12', 'Medium'], ['-6', 'Loud']] },
      { name: 'duck', label: 'Dip the music while someone talks', type: 'check', value: true }] },
  { id: 'join', title: 'Join videos', endpoint: '/api/quick/join', go: 'Join the videos',
    blurb: 'Join 2 to 6 videos one after another into a single file, in the order you pick them. Every clip is fitted to the size of the first.',
    fields: [
      { name: 'videos', label: 'Videos (2 to 6, in order)', type: 'file', accept: VIDEO_ACCEPT, multiple: true, required: true, wide: true }] },
  { id: 'pip', title: 'Picture in picture', endpoint: '/api/quick/pip', go: 'Combine the videos',
    blurb: 'Put a small video (a face camera, say) over a corner of the main one. The sound comes from the main video.',
    fields: [
      { name: 'video', label: 'Video', type: 'file', accept: VIDEO_ACCEPT, required: true, wide: true },
      { name: 'overlay', label: 'Small video', type: 'file', accept: VIDEO_ACCEPT, required: true, wide: true },
      { name: 'corner', label: 'Corner', type: 'select', value: 'br', options: [['br', 'Bottom right'], ['bl', 'Bottom left'], ['tr', 'Top right'], ['tl', 'Top left']] },
      { name: 'size', label: 'Small video size (% of the width)', type: 'number', min: 15, max: 40, value: 25 }] },
  {"id": "zoom", "title": "Zoom in", "endpoint": "/api/quick/zoom", "go": "Zoom in", "blurb": "Punch in on the middle or a corner, like a crop-in on the action. The result keeps the video's size.", "fields": [{"name": "video", "label": "Video", "type": "file", "accept": VIDEO_ACCEPT, "required": true, "wide": true}, {"name": "amount", "label": "Zoom", "type": "select", "value": "125", "options": [["110", "10%"], ["125", "25%"], ["150", "50%"], ["200", "2x"]]}, {"name": "anchor", "label": "Zoom toward", "type": "select", "value": "center", "options": [["center", "Center"], ["tl", "Top left"], ["tr", "Top right"], ["bl", "Bottom left"], ["br", "Bottom right"]]}]},
  {"id": "letterbox", "title": "Add borders", "endpoint": "/api/quick/letterbox", "go": "Add the borders", "blurb": "Fit a video inside a new shape with bars around it instead of cropping. Handy for putting a vertical clip on a wide canvas.", "fields": [{"name": "video", "label": "Video", "type": "file", "accept": VIDEO_ACCEPT, "required": true, "wide": true}, {"name": "shape", "label": "New shape", "type": "select", "value": "16:9", "options": [["16:9", "Wide 16:9"], ["9:16", "Vertical 9:16"], ["1:1", "Square 1:1"], ["4:5", "Portrait 4:5"]]}, {"name": "color", "label": "Bar color", "type": "text", "value": "#000000", "max": 7}]},
  {"id": "hold", "title": "Hold first / last frame", "endpoint": "/api/quick/hold", "go": "Hold the frames", "blurb": "Freeze the first frame before the video starts and the last frame after it ends, up to 10 seconds each.", "fields": [{"name": "video", "label": "Video", "type": "file", "accept": VIDEO_ACCEPT, "required": true, "wide": true}, {"name": "start", "label": "Hold the start (seconds)", "type": "number", "min": 0, "max": 10, "value": 0}, {"name": "end", "label": "Hold the end (seconds)", "type": "number", "min": 0, "max": 10, "value": 2}]},
  {"id": "cut", "title": "Cut out a part", "endpoint": "/api/quick/cut", "go": "Cut it out", "blurb": "Remove a section from the middle and join the two sides together. Give the start and end of the part to delete.", "fields": [{"name": "video", "label": "Video", "type": "file", "accept": VIDEO_ACCEPT, "required": true, "wide": true}, {"name": "start", "label": "Delete from (seconds)", "type": "number", "min": 0, "max": 100000, "value": 0}, {"name": "end", "label": "Delete until (seconds)", "type": "number", "min": 0, "max": 100000, "value": 0}]},
  {"id": "look", "title": "Looks", "endpoint": "/api/quick/look", "go": "Apply the look", "blurb": "One-click looks: black and white, sepia, warm, cool and more.", "fields": [{"name": "video", "label": "Video", "type": "file", "accept": VIDEO_ACCEPT, "required": true, "wide": true}, {"name": "look", "label": "Look", "type": "select", "value": "warm", "options": [["bw", "Black and white"], ["sepia", "Sepia"], ["warm", "Warm"], ["cool", "Cool"], ["vivid", "Vivid"], ["faded", "Faded"], ["vignette", "Dark edges"]]}]},
  {"id": "side", "title": "Side by side", "endpoint": "/api/quick/side", "go": "Combine them", "blurb": "Show two videos next to each other or one above the other. It ends with the shorter one and uses the first video's sound.", "fields": [{"name": "video", "label": "Video", "type": "file", "accept": VIDEO_ACCEPT, "required": true, "wide": true}, {"name": "second", "label": "Second video", "type": "file", "accept": VIDEO_ACCEPT, "required": true, "wide": true}, {"name": "layout", "label": "Layout", "type": "select", "value": "h", "options": [["h", "Side by side"], ["v", "One above the other"]]}]},
  {"id": "slides", "title": "Slideshow", "endpoint": "/api/quick/slides", "go": "Make the slideshow", "blurb": "Turn 2 to 10 pictures into a video with soft fades, with an optional song underneath.", "fields": [{"name": "images", "label": "Pictures (2 to 10, in order)", "type": "file", "accept": IMG_ACCEPT, "multiple": true, "required": true, "wide": true}, {"name": "audio", "label": "Song (optional)", "type": "file", "accept": AUDIO_ACCEPT, "wide": true}, {"name": "each", "label": "Seconds per picture", "type": "number", "min": 2, "max": 8, "value": 4}, {"name": "shape", "label": "Shape", "type": "select", "value": "landscape", "options": [["landscape", "Wide 16:9"], ["portrait", "Vertical 9:16"], ["square", "Square 1:1"]]}]},
  {"id": "text", "title": "Text on video", "endpoint": "/api/quick/text", "go": "Add the text", "blurb": "Burn a line of text onto a video in your Brand kit font and colors. Use *stars* around a word to highlight it.", "fields": [{"name": "video", "label": "Video", "type": "file", "accept": VIDEO_ACCEPT, "required": true, "wide": true}, {"name": "text", "label": "Text", "type": "text", "required": true, "wide": true, "max": 140}, {"name": "position", "label": "Where", "type": "select", "value": "bottom", "options": [["top", "Top"], ["center", "Middle"], ["bottom", "Bottom"]]}, {"name": "size", "label": "Size", "type": "select", "value": "medium", "options": [["small", "Small"], ["medium", "Medium"], ["large", "Large"]]}, {"name": "start", "label": "Show from (seconds)", "type": "number", "min": 0, "max": 100000, "value": 0}, {"name": "length", "label": "Show for (seconds, 0 = until the end)", "type": "number", "min": 0, "max": 600, "value": 0}]},
  {"id": "xfade", "title": "Crossfade join", "endpoint": "/api/quick/xfade", "go": "Join with a crossfade", "blurb": "Join two videos with a soft dissolve between them. You only get sound if both videos have it.", "fields": [{"name": "video", "label": "Video", "type": "file", "accept": VIDEO_ACCEPT, "required": true, "wide": true}, {"name": "second", "label": "Second video", "type": "file", "accept": VIDEO_ACCEPT, "required": true, "wide": true}, {"name": "fade", "label": "Fade length (seconds)", "type": "number", "min": 0.5, "max": 3, "value": 1}]},
  {"id": "atrim", "title": "Trim audio", "endpoint": "/api/quick/atrim", "go": "Trim the audio", "blurb": "Keep one part of a song or recording. Works on a video's sound too, and gives you an audio file.", "fields": [{"name": "audio", "label": "Audio or video", "type": "file", "accept": AUDIO_ACCEPT, "required": true, "wide": true}, {"name": "start", "label": "Start (seconds)", "type": "number", "min": 0, "max": 100000, "value": 0}, {"name": "end", "label": "End (seconds, 0 = the end)", "type": "number", "min": 0, "max": 100000, "value": 0}]},
  {"id": "afade", "title": "Audio fades", "endpoint": "/api/quick/afade", "go": "Add the fades", "blurb": "Fade a sound in at the start and out at the end.", "fields": [{"name": "audio", "label": "Audio or video", "type": "file", "accept": AUDIO_ACCEPT, "required": true, "wide": true}, {"name": "fade_in", "label": "Fade in (seconds)", "type": "number", "min": 0, "max": 30, "value": 2}, {"name": "fade_out", "label": "Fade out (seconds)", "type": "number", "min": 0, "max": 30, "value": 2}]},
  {"id": "aspeed", "title": "Audio speed", "endpoint": "/api/quick/aspeed", "go": "Change the speed", "blurb": "Play a sound slower or faster. Speech stays natural at moderate speeds.", "fields": [{"name": "audio", "label": "Audio or video", "type": "file", "accept": AUDIO_ACCEPT, "required": true, "wide": true}, {"name": "factor", "label": "Speed", "type": "select", "value": "1.25", "options": [["0.5", "0.5x"], ["0.75", "0.75x"], ["1.25", "1.25x"], ["1.5", "1.5x"], ["2", "2x"]]}]},
  {"id": "tone", "title": "Bass and treble", "endpoint": "/api/quick/tone", "go": "Adjust the tone", "blurb": "Lift or lower the low and high end of a sound. Move at least one slider (-12 to 12 dB).", "fields": [{"name": "audio", "label": "Audio or video", "type": "file", "accept": AUDIO_ACCEPT, "required": true, "wide": true}, {"name": "bass", "label": "Bass (dB)", "type": "number", "min": -12, "max": 12, "value": 0}, {"name": "treble", "label": "Treble (dB)", "type": "number", "min": -12, "max": 12, "value": 0}]},
  {"id": "channels", "title": "Mono / swap sides", "endpoint": "/api/quick/channels", "go": "Change the channels", "blurb": "Fold a sound down to mono, or swap its left and right sides.", "fields": [{"name": "audio", "label": "Audio or video", "type": "file", "accept": AUDIO_ACCEPT, "required": true, "wide": true}, {"name": "mode", "label": "Do this", "type": "select", "value": "mono", "options": [["mono", "Make it mono"], ["swap", "Swap left and right"]]}]},
  {"id": "ajoin", "title": "Join audio", "endpoint": "/api/quick/ajoin", "go": "Join the audio", "blurb": "Join 2 to 6 sounds one after another into a single audio file.", "fields": [{"name": "audios", "label": "Audio files (2 to 6, in order)", "type": "file", "accept": AUDIO_ACCEPT, "multiple": true, "required": true, "wide": true}]},
  {"id": "silence", "title": "Remove silence", "endpoint": "/api/quick/silence", "go": "Remove the silence", "blurb": "Cut the quiet from the start and end of a recording, or shorten the long pauses in the middle.", "fields": [{"name": "audio", "label": "Audio or video", "type": "file", "accept": AUDIO_ACCEPT, "required": true, "wide": true}, {"name": "mode", "label": "Remove", "type": "select", "value": "ends", "options": [["ends", "Silence at the start and end"], ["pauses", "Long pauses in the middle"]]}, {"name": "level", "label": "What counts as silence", "type": "select", "value": "-50", "options": [["-40", "Quiet room noise too"], ["-50", "Normal"], ["-60", "Only true silence"]]}]},
  {"id": "aloop", "title": "Loop audio", "endpoint": "/api/quick/aloop", "go": "Loop the audio", "blurb": "Repeat a sound 2, 3, 5 or 10 times in a row.", "fields": [{"name": "audio", "label": "Audio or video", "type": "file", "accept": AUDIO_ACCEPT, "required": true, "wide": true}, {"name": "times", "label": "Repeat", "type": "select", "value": "3", "options": [["2", "2 times"], ["3", "3 times"], ["5", "5 times"], ["10", "10 times"]]}]},
  {"id": "pitch", "title": "Pitch shift", "endpoint": "/api/quick/pitch", "go": "Shift the pitch", "blurb": "Raise or lower the pitch by up to an octave. The length stays the same.", "fields": [{"name": "audio", "label": "Audio or video", "type": "file", "accept": AUDIO_ACCEPT, "required": true, "wide": true}, {"name": "semitones", "label": "Semitones", "type": "select", "value": "2", "options": [["-12", "-12 (one octave)"], ["-11", "-11"], ["-10", "-10"], ["-9", "-9"], ["-8", "-8"], ["-7", "-7"], ["-6", "-6"], ["-5", "-5"], ["-4", "-4"], ["-3", "-3"], ["-2", "-2"], ["-1", "-1"], ["1", "+1"], ["2", "+2"], ["3", "+3"], ["4", "+4"], ["5", "+5"], ["6", "+6"], ["7", "+7"], ["8", "+8"], ["9", "+9"], ["10", "+10"], ["11", "+11"], ["12", "+12 (one octave)"]]}]},
  {"id": "echo", "title": "Echo", "endpoint": "/api/quick/echo", "go": "Add the echo", "blurb": "Add a slapback echo, a small room or a large hall to a sound.", "fields": [{"name": "audio", "label": "Audio or video", "type": "file", "accept": AUDIO_ACCEPT, "required": true, "wide": true}, {"name": "style", "label": "Style", "type": "select", "value": "room", "options": [["slap", "Slapback"], ["room", "Small room"], ["hall", "Large hall"]]}]},
  {"id": "collage", "title": "Collage", "endpoint": "/api/quick/collage", "go": "Make the collage", "blurb": "Lay 2 to 9 pictures out in a neat grid in one image.", "fields": [{"name": "images", "label": "Pictures (in order)", "type": "file", "accept": IMG_ACCEPT, "multiple": true, "required": true, "wide": true}, {"name": "gap", "label": "Gap between them", "type": "select", "value": "12", "options": [["0", "None"], ["12", "Small"], ["28", "Large"]]}]},
  {"id": "frame_shot", "title": "Frame a screenshot", "endpoint": "/api/quick/frame_shot", "go": "Frame it", "blurb": "Put a screenshot on a brand-colored background with rounded corners and a soft shadow. Good for plugin screenshots.", "fields": [{"name": "image", "label": "Screenshot (PNG or JPG)", "type": "file", "accept": IMG_ACCEPT, "required": true, "wide": true}, {"name": "pad", "label": "Space around it (%)", "type": "number", "min": 3, "max": 20, "value": 8}, {"name": "radius", "label": "Corners", "type": "select", "value": "4", "options": [["0", "Square"], ["2", "Slightly rounded"], ["4", "Rounded"], ["7", "Very rounded"]]}, {"name": "shadow", "label": "Drop shadow", "type": "check", "value": true}]},
  {"id": "palette", "title": "Color palette", "endpoint": "/api/quick/palette", "go": "Get the palette", "blurb": "Find the main colors in a picture and show them as swatches with their hex codes.", "fields": [{"name": "image", "label": "Picture (PNG or JPG)", "type": "file", "accept": IMG_ACCEPT, "required": true, "wide": true}, {"name": "count", "label": "Colors", "type": "select", "value": "5", "options": [["4", "4"], ["5", "5"], ["6", "6"], ["8", "8"]]}]},
  {"id": "compare", "title": "Before / after picture", "endpoint": "/api/quick/compare", "go": "Make the comparison", "blurb": "Split two pictures down the middle (or across) with labels, to show a change.", "fields": [{"name": "image", "label": "Before picture", "type": "file", "accept": IMG_ACCEPT, "required": true, "wide": true}, {"name": "second", "label": "After picture", "type": "file", "accept": IMG_ACCEPT, "required": true, "wide": true}, {"name": "split", "label": "Split", "type": "select", "value": "vertical", "options": [["vertical", "Left and right"], ["horizontal", "Top and bottom"]]}, {"name": "before", "label": "Before label", "type": "text", "value": "Before", "max": 20}, {"name": "after", "label": "After label", "type": "text", "value": "After", "max": 20}]},
  {"id": "banner", "title": "YouTube banner", "endpoint": "/api/quick/banner", "go": "Make the banner", "blurb": "A 2560 x 1440 channel banner in your Brand kit colors, with the name kept inside the area every device shows. Uses your Brand kit logo if you saved one.", "fields": [{"name": "name", "label": "Channel name", "type": "text", "required": true, "wide": true, "max": 40}, {"name": "tagline", "label": "Tagline (optional)", "type": "text", "wide": true, "max": 70}]},
  {"id": "avatar", "title": "Profile picture", "endpoint": "/api/quick/avatar", "go": "Make the profile picture", "blurb": "Cut a picture into a circle or rounded square for a channel or profile icon, with a transparent background.", "fields": [{"name": "image", "label": "Picture (PNG or JPG)", "type": "file", "accept": IMG_ACCEPT, "required": true, "wide": true}, {"name": "size", "label": "Size", "type": "select", "value": "512", "options": [["256", "256 px"], ["512", "512 px"], ["1024", "1024 px"]]}, {"name": "shape", "label": "Shape", "type": "select", "value": "circle", "options": [["circle", "Circle"], ["rounded", "Rounded square"]]}]},
  {"id": "dropclip", "title": "Clip around the drop", "endpoint": "/api/quick/dropclip", "go": "Find the drop and cut the clip", "blurb": "Finds the drop (the moment the song gets big) in a music video or any video with sound, and cuts a clip that starts a few seconds before it. Vertical by default, ready for Shorts. Songs up to 15 minutes.", "fields": [{"name": "video", "label": "Video", "type": "file", "accept": VIDEO_ACCEPT, "required": true, "wide": true}, {"name": "length", "label": "Clip length", "type": "select", "value": "30", "options": [["15", "15 seconds"], ["30", "30 seconds"], ["45", "45 seconds"], ["60", "60 seconds"]]}, {"name": "pre", "label": "Start before the drop", "type": "select", "value": "5", "options": [["3", "3 seconds"], ["5", "5 seconds"], ["8", "8 seconds"]]}, {"name": "shape", "label": "Shape", "type": "select", "value": "9:16", "options": [["9:16", "Vertical 9:16"], ["1:1", "Square 1:1"], ["original", "Keep the original shape"]]}]},
  {"id": "dropaudio", "title": "Best part of a song", "endpoint": "/api/quick/dropaudio", "go": "Cut the best part", "blurb": "Cuts the most exciting stretch of a song, starting just before the drop, with short fades. Good for previews and teasers. Gives you an audio file.", "fields": [{"name": "audio", "label": "Song (audio or video)", "type": "file", "accept": AUDIO_ACCEPT, "required": true, "wide": true}, {"name": "length", "label": "Length", "type": "select", "value": "30", "options": [["15", "15 seconds"], ["30", "30 seconds"], ["45", "45 seconds"], ["60", "60 seconds"]]}, {"name": "pre", "label": "Start before the drop", "type": "select", "value": "5", "options": [["3", "3 seconds"], ["5", "5 seconds"], ["8", "8 seconds"]]}]},
  {"id": "songcard", "title": "Song analysis", "endpoint": "/api/quick/songcard", "go": "Analyze the song", "blurb": "A picture of what a song is like: tempo, loudness, where the drop is, the best 30 seconds, and how the energy moves. Tempo can be unreliable on live or free-time music.", "fields": [{"name": "audio", "label": "Song (audio or video)", "type": "file", "accept": AUDIO_ACCEPT, "required": true, "wide": true}]}
];
/* Which kind of thing each tab makes, so 60-odd tabs can be filtered to a handful. */
const GROUPS = [['all', 'All'], ['create', 'Create'], ['video', 'Edit video'], ['audio', 'Audio'], ['picture', 'Pictures']];
const GROUP_OF = {
  create: ['dropclip', 'mv', 'anim', 'stream', 'ab', 'viz', 'gif', 'lower', 'quote', 'still', 'slides', 'text', 'sheet', 'banner'],
  audio: ['dropaudio', 'songcard', 'enhance', 'extract', 'swap', 'volume', 'atrim', 'afade', 'aspeed', 'tone', 'channels', 'ajoin', 'silence', 'aloop', 'pitch', 'echo', 'music', 'waveform'],
  picture: ['frame', 'collage', 'frame_shot', 'palette', 'compare', 'avatar'],
};
const groupOf = (id) => Object.keys(GROUP_OF).find((g) => GROUP_OF[g].includes(id)) || 'video';
const SCENE_LABEL = { intro: 'Intro', starting: 'Starting soon', brb: 'Be right back', ending: 'Ending' };
const state = { tab: null, inputs: new Map(), busy: false, buttons: [], caps: null, group: 'all', query: '' };

/* Remember the last tab and the settings used in each (not files), so a repeated job is one click. Storage can be blocked: always optional. */
const MEMORY_KEY = 'skellymotion.make.v1';
const memLoad = () => { try { const m = JSON.parse(localStorage.getItem(MEMORY_KEY) || '{}'); return m && typeof m === 'object' ? m : {}; } catch (e) { return {}; } };
const memSave = (mutate) => { try { const m = memLoad(); mutate(m); localStorage.setItem(MEMORY_KEY, JSON.stringify(m)); } catch (e) { /* private window or blocked */ } };
function remember(tab) {
  memSave((m) => {
    m.tab = tab.id; m.values = m.values || {}; m.kindTab = m.kindTab || {}; const saved = {};
    for (const k of Object.keys(kindAccepts)) if (fitsKind(tab, k)) m.kindTab[k] = tab.id;
    for (const field of tab.fields) {
      const node = state.inputs.get(field.name);
      if (!node || !node.ctl || field.type === 'file' || field.type === 'checks') continue;
      saved[field.name] = field.type === 'check' ? !!node.ctl.checked : String(node.ctl.value ?? '').slice(0, 400);
    }
    m.values[tab.id] = saved;
  });
}
function restore(tab) {
  const saved = (memLoad().values || {})[tab.id]; if (!saved || typeof saved !== 'object') return;
  for (const field of tab.fields) {
    const node = state.inputs.get(field.name); const v = saved[field.name];
    if (!node || !node.ctl || v === undefined || field.type === 'file' || field.type === 'checks') continue;
    if (field.type === 'check') { if (typeof v === 'boolean') node.ctl.checked = v; continue; }
    if (field.type === 'select' && !field.options.some(([value]) => value === v)) continue;
    node.ctl.value = String(v);
  }
}
/* Filters this FFmpeg lacks (a minimal build): the page greys the tool out instead of failing half way. Unknown means allowed. */
const missingFor = (tab) => (state.caps && state.caps.tools && state.caps.tools[tab.id] && state.caps.tools[tab.id].missing) || [];


const sizeText = (bytes) => bytes >= 1048576 ? (bytes / 1048576).toFixed(bytes >= 10485760 ? 0 : 1) + ' MB' : Math.max(1, Math.round(bytes / 1024)) + ' KB';
function showPicked(wrap, input) {
  const files = Array.from(input.files || []);
  if (!wrap.picked) { wrap.picked = ui().el('small', { class: 'make-picked' }); wrap.append(wrap.picked); }
  wrap.picked.textContent = files.length ? files.map((f) => f.name + (f.size ? ' (' + sizeText(f.size) + ')' : '')).join(', ') : '';
}

function fieldNode(field) {
  const { el } = ui();
  let input; const wrap = el('label', { class: 'make-field' + (field.wide ? ' wide' : '') + (field.type === 'check' ? ' check' : '') + (field.type === 'file' ? ' make-file' : '') + (field.required ? ' required' : '') });
  if (field.type === 'select') {
    input = el('select', { name: field.name }, ...field.options.map(([value, text]) => el('option', { value, text })));
    input.value = field.value;
  } else if (field.type === 'textarea') {
    input = el('textarea', { name: field.name, rows: '5', maxlength: '1200' }); input.value = field.value || '';
  } else if (field.type === 'check') {
    input = el('input', { type: 'checkbox', name: field.name }); input.checked = !!field.value;
  } else if (field.type === 'file') {
    input = el('input', { type: 'file', name: field.name, accept: field.accept, multiple: field.multiple });
    input.addEventListener('change', () => showPicked(wrap, input));
  } else if (field.type === 'checks') {
    const boxes = field.options.map(([value, text]) => {
      const box = el('input', { type: 'checkbox', value }); box.checked = field.value.includes(value);
      return { box, node: el('label', { class: 'lang-chip' }, box, text) };
    });
    const group = el('div', { class: 'lang-grid' }, ...boxes.map((b) => b.node));
    group.boxes = boxes.map((b) => b.box);
    const block = el('div', { class: 'make-field wide' }, el('span', { text: field.label }), group);
    block.ctl = group; return block;
  } else {
    input = el('input', { type: field.type === 'number' ? 'number' : 'text', name: field.name, maxlength: field.max, min: field.min, max: field.max });
    input.value = field.value !== undefined ? String(field.value) : '';
  }
  if (field.type === 'check') wrap.append(input, field.label);
  else wrap.append(ui().el('span', { text: field.label }), input);
  if (field.hint) wrap.append(ui().el('small', { text: field.hint }));
  wrap.ctl = input; return wrap;
}

function readForm(tab) {
  const form = new FormData(); const problems = [];
  for (const field of tab.fields) {
    const node = state.inputs.get(field.name); if (!node || node.hidden) continue;
    const input = node.ctl;
    if (field.type === 'file') {
      const files = Array.from(input.files || []);
      if (field.required && !files.length) problems.push(field.label);
      for (const f of files) form.append(field.name, f);
    } else if (field.type === 'checks') {
      const picked = input.boxes.filter((b) => b.checked).map((b) => b.value);
      if (!picked.length) problems.push(field.label);
      form.append(field.name, picked.join(','));
    } else if (field.type === 'check') form.append(field.name, input.checked ? 'true' : 'false');
    else {
      if (field.required && !String(input.value ?? '').trim()) problems.push(field.label);
      form.append(field.name, String(input.value ?? ''));
    }
  }
  return { form, problems };
}

function applyVisibility(tab) {
  for (const field of tab.fields) {
    if (!field.showIf) continue;
    const node = state.inputs.get(field.name);
    const show = Object.entries(field.showIf).every(([name, value]) => { const n = state.inputs.get(name); return n && n.ctl.value === value; });
    node.hidden = !show; node.classList.toggle('hidden', !show);
  }
}

function paintTab(tab) {
  const { el } = ui();
  state.tab = tab; state.inputs = new Map();
  for (const b of state.buttons) { b.node.classList.toggle('active', b.id === tab.id); b.node.setAttribute('aria-selected', String(b.id === tab.id)); }
  $('makeBlurb').textContent = tab.blurb;
  const heading = $('makeToolTitle');
  if (heading) { heading.textContent = tab.title; heading.className = 'make-tool-title g-' + groupOf(tab.id); heading.setAttribute('data-kind', (GROUPS.find(([id]) => id === groupOf(tab.id)) || [0, ''])[1]); }
  if (state.buttons.length) applyFilter();
  const active = state.buttons.find((b) => b.id === tab.id);  // the chosen tab must never sit out of sight in the scrolled list
  const strip = $('makeTabs');  // scroll only the tab list itself (scrollIntoView would also move the whole page)
  if (active && strip && typeof active.node.offsetTop === 'number' && strip.clientHeight) strip.scrollTop = Math.max(0, active.node.offsetTop - strip.offsetTop - (strip.clientHeight - active.node.offsetHeight) / 2);
  const nodes = tab.fields.map((field) => { const node = fieldNode(field); state.inputs.set(field.name, node); return node; });
  for (const field of tab.fields) {
    const node = state.inputs.get(field.name);
    if (!node.ctl.addEventListener) continue;
    node.ctl.addEventListener('change', () => applyVisibility(tab));
  }
  const go = el('button', { type: 'button', class: 'primary-btn make-go', id: 'makeGo', text: tab.go, onclick: () => run(tab) });
  $('makeForm').replaceChildren(...nodes, go);
  restore(tab);
  applyVisibility(tab);
  const missing = missingFor(tab);
  if (missing.length) { $('makeBlurb').textContent = tab.blurb + ' This FFmpeg build is missing: ' + missing.join(', ') + '.'; go.disabled = true; }
  $('makeResults').replaceChildren(); $('makeStatus').classList.add('hidden');
}

function infoLine(out) {
  const bits = [];
  if (out.bpm) bits.push(Math.round(out.bpm) + ' BPM' + (out.confidence !== undefined ? ' (' + Math.round(out.confidence * 100) + '% sure)' : ''));
  if (out.cuts) bits.push(out.cuts + ' cuts from ' + out.clips + ' clip' + (out.clips === 1 ? '' : 's'));
  if (out.seconds && !out.scenes) bits.push(Math.round(out.seconds) + ' s');
  if (out.matched) bits.push('loudness matched (' + out.gain_db + ' dB on the second file)');
  return bits.join(' · ');
}
function resultCard(label, url, kind, name, bytes) {
  const { el } = ui();
  const media = kind === 'image' ? el('img', { class: 'ae-thumb', src: url, alt: label })
    : kind === 'audio' ? el('audio', { controls: true, preload: 'metadata', src: url }) : el('video', { controls: true, preload: 'metadata', src: url });
  return el('div', { class: 'auto-result' }, el('strong', { text: label }), media,
    el('div', { class: 'auto-actions' }, el('a', { class: 'download-btn', href: url, download: '', text: 'Download' + (bytes ? ' (' + sizeText(bytes) + ')' : '') }), furtherMenu(label, url, kind, name)));
}
function furtherMenu(label, url, kind, name) {
  const { el } = ui(); const k = kind || 'video';
  const targets = TABS.filter((t) => fitsKind(t, k) && !(state.tab && t.id === state.tab.id));
  if (!name || !targets.length) return el('span');
  const pick = el('select', { class: 'further', 'aria-label': 'Edit this further' }, el('option', { value: '', text: 'Edit this further…' }), ...targets.map((t) => el('option', { value: t.id, text: t.title })));
  pick.addEventListener('change', () => { if (pick.value) { const id = pick.value; pick.value = ''; carryOver({ url, name }, id); } });
  return pick;
}
function showResults(out) {
  const { el } = ui(); const box = $('makeResults'); box.replaceChildren();
  const line = infoLine(out); if (line) box.append(el('small', { class: 'auto-reasons', text: line }));
  if (out.warning) box.append(el('small', { class: 'make-warning', text: out.warning }));
  if (out.video) box.append(resultCard('Your video', out.video));
  for (const s of out.scenes || []) box.append(resultCard((SCENE_LABEL[s.scene] || s.scene) + (s.loop ? ' (loops)' : ''), s.video));
  for (const f of out.files || []) box.append(resultCard(f.label || f.name, f.url, f.kind, f.name, f.bytes));
}

const ago = (seconds) => {
  const d = Math.max(0, Date.now() / 1000 - seconds);
  return d < 90 ? 'just now' : d < 5400 ? Math.round(d / 60) + ' min ago' : d < 129600 ? Math.round(d / 3600) + ' h ago' : Math.round(d / 86400) + ' days ago';
};
async function loadRecent() {
  const box = $('makeRecent'); if (!box || !ui()) return;
  const { el, api, toast: say } = ui();
  try {
    const { makes } = await api('/api/makes');
    box.replaceChildren(...(makes.length ? [el('div', { class: 'auto-actions' }, el('strong', { text: 'Recent (kept for 3 days)' }),
      el('button', { type: 'button', class: 'tiny-btn', id: 'makeClearAll', text: 'Clear all', onclick: async () => {
        try { const r = await api('/api/makes', { method: 'DELETE' }); say(r.deleted + ' removed' + (r.skipped ? ', ' + r.skipped + ' still rendering' : '') + '.'); loadRecent(); } catch (e) { say(e.message, true); }
      } })), ...makes.map((m) => el('div', { class: 'recent-row' },
      el('div', {}, el('b', { text: m.label }), el('small', { text: (m.title ? ' · ' + m.title : '') + ' · ' + ago(m.created) })),
      el('div', { class: 'auto-actions' },
        ...(m.busy ? [el('small', { class: 'auto-reasons', text: 'Still rendering…' })] : m.files.map((f) => el('a', { class: 'tiny-btn', href: f.url, target: '_blank', rel: 'noopener', text: f.name }))),
        m.busy ? null : el('button', { type: 'button', class: 'tiny-btn', text: 'Delete', onclick: async () => {
          try { await api('/api/makes/' + encodeURIComponent(m.id), { method: 'DELETE' }); loadRecent(); } catch (e) { say(e.message, true); }
        } }))))] : []));
  } catch (e) { /* the list is a convenience */ }
}

// Buttons under an Auto-edit result: vertical and square versions, and three thumbnail layouts. Called by static/autoclip.js.
function extras(out, id) {
  const { el, api, post, runJob, showStatus, toast: say } = ui();
  const status = el('div', { class: 'ae-status hidden' }); const results = el('div', { class: 'auto-results' });
  let busy = false;
  const start = (label, path, body, button) => async () => {
    if (busy) return; busy = true; button.disabled = true;
    try {
      const { job_id } = await post(path, body);
      const job = await runJob(job_id, (j) => showStatus(status, j));
      status.classList.add('hidden'); results.replaceChildren();
      for (const f of (job.outputs || {}).files || []) results.append(resultCard(f.label || f.name, f.url, f.kind));
    } catch (e) { status.classList.remove('hidden'); status.textContent = 'Stopped: ' + e.message; say(e.message, true); }
    finally { busy = false; button.disabled = false; }
  };
  const vertical = el('button', { type: 'button', class: 'tiny-btn', id: 'aeRepurpose', text: 'Make vertical and square versions' });
  const thumbs = el('button', { type: 'button', class: 'tiny-btn', id: 'aeThumbs', text: 'Thumbnail variants' });
  const fill = el('button', { type: 'button', class: 'tiny-btn', id: 'aeVerticalFill', text: 'Vertical, cropped to fill' });
  vertical.addEventListener('click', start('repurpose', '/api/projects/' + encodeURIComponent(id) + '/repurpose', { formats: ['portrait', 'square'], resolution: '1080p' }, vertical));
  fill.addEventListener('click', start('repurpose', '/api/projects/' + encodeURIComponent(id) + '/repurpose', { formats: ['portrait'], resolution: '1080p', fit: 'fill' }, fill));
  thumbs.addEventListener('click', start('thumbs', '/api/projects/' + encodeURIComponent(id) + '/thumbnails', { title: out.youtube && out.youtube.title || '' }, thumbs));
  return [el('div', { class: 'auto-result' }, el('strong', { text: 'More from this video' }),
    el('small', { class: 'auto-reasons', text: 'Vertical and square versions put the picture over a blurred copy of itself; burned-in captions get smaller with it. Cropped to fill has no blurred bars but loses the sides of the picture.' }),
    el('div', { class: 'auto-actions' }, vertical, fill, thumbs), status, results)];
}

async function run(tab) {
  if (state.busy) return;
  const { form, problems } = readForm(tab);
  if (missingFor(tab).length) { toast('This tool needs FFmpeg filters that are missing from this build.', true); return; }
  for (const node of state.inputs.values()) if (node.classList) node.classList.remove('invalid');
  if (problems.length) {
    const flagged = tab.fields.filter((f) => problems.includes(f.label)).map((f) => state.inputs.get(f.name)).filter(Boolean);
    flagged.forEach((n) => n.classList && n.classList.add('invalid'));
    if (flagged[0] && flagged[0].scrollIntoView) flagged[0].scrollIntoView({ block: 'center', behavior: 'smooth' });
    toast('Still needed: ' + problems.join(', ') + '.', true); return;
  }
  remember(tab);
  state.busy = true; const go = $('makeGo'); if (go) go.disabled = true;
  const status = $('makeStatus'); status.classList.remove('hidden'); status.textContent = 'Uploading…';
  try {
    const { job_id } = await ui().api(tab.endpoint, { method: 'POST', body: form });
    const job = await ui().runJob(job_id, (j) => ui().showStatus(status, j));
    status.textContent = 'Done.';
    showResults(job.outputs || {});
    loadRecent();
  } catch (e) { status.classList.remove('hidden'); status.textContent = 'Stopped: ' + e.message; toast(e.message, true); }
  finally { state.busy = false; if (go) go.disabled = false; }
}

function tabMatches(tab) {
  const q = state.query.trim().toLowerCase();
  if (state.tab && state.tab.id === tab.id) return true;
  if (q) return (tab.title + ' ' + tab.blurb).toLowerCase().includes(q);
  return state.group === 'all' || groupOf(tab.id) === state.group;
}
function applyFilter() {
  const bar = $('makeGroups');
  if (bar) GROUPS.forEach(([id], n) => { const c = bar.children[n]; if (c) c.classList.toggle('active', id === state.group && !state.query.trim()); });
  for (const b of state.buttons) b.node.classList.toggle('hidden', !tabMatches(TABS.find((t) => t.id === b.id)));
}
function showGroup(group) { state.group = group; state.query = ''; const box = $('makeSearch'); if (box) box.value = ''; memSave((m) => { m.group = group; }); applyFilter(); }
function search(text) { state.query = String(text || '').slice(0, 40); applyFilter(); }

/* Hand a finished result to another tool: fetch it back as a file and fill that tool's first file field. */
const kindAccepts = { video: [VIDEO_ACCEPT, AUDIO_ACCEPT], audio: [AUDIO_ACCEPT], image: [IMG_ACCEPT] };
const firstFile = (tab) => tab.fields.find((f) => f.type === 'file');
const fitsKind = (tab, kind) => { const f = firstFile(tab); return !!f && (kindAccepts[kind] || []).includes(f.accept); };
async function carryOver(file, tabId) {
  const tab = TABS.find((t) => t.id === tabId); if (!tab || state.busy) return;
  paintTab(tab);
  const node = state.inputs.get(firstFile(tab).name);
  try {
    const bytes = await (await fetch(file.url)).blob();
    const picked = typeof File === 'function' ? new File([bytes], file.name, { type: bytes.type }) : { name: file.name, size: bytes.size };
    if (typeof DataTransfer === 'function') { const dt = new DataTransfer(); dt.items.add(picked); node.ctl.files = dt.files; } else node.ctl.files = [picked];
    showPicked(node, node.ctl);
    toast('Loaded into ' + tab.title + '. Adjust the settings and press the button.');
  } catch (e) { toast('Could not reuse that file. Download it and choose it again.', true); }
}
const dragKind = (file) => {
  const name = String(file.name || '').toLowerCase(), type = String(file.type || '');
  if (type.startsWith('image/') || /\.(png|jpe?g)$/.test(name)) return 'image';
  if (type.startsWith('audio/') || /\.(mp3|wav|m4a|aac|flac|ogg|opus)$/.test(name)) return 'audio';
  return /\.(mp4|mov|mkv|webm|m4v)$/.test(name) || type.startsWith('video/') ? 'video' : '';
};
function dropFiles(files) {
  const list = Array.from(files || []); if (!list.length || state.busy) return;
  const kind = dragKind(list[0]); if (!kind) { toast('That file type is not supported here. Use a video, audio or picture file.', true); return; }
  const tab = state.tab && fitsKind(state.tab, kind) ? state.tab : TABS.find((t) => fitsKind(t, kind) && t.id === (memLoad().kindTab || {})[kind]) || TABS.find((t) => fitsKind(t, kind) && !firstFile(t).multiple) || TABS.find((t) => fitsKind(t, kind));
  paintTab(tab);
  const f = firstFile(tab), node = state.inputs.get(f.name);
  node.ctl.files = f.multiple ? list : [list[0]]; showPicked(node, node.ctl);
}

function open(tabId) {
  const { el } = ui();
  if (!state.buttons.length) {
    state.buttons = TABS.map((t) => ({ id: t.id, node: el('button', { type: 'button', class: 'make-tab g-' + groupOf(t.id), role: 'tab', text: t.title,
      onclick: () => { if (!state.busy) paintTab(t); } }) }));
    $('makeTabs').replaceChildren(...state.buttons.map((b) => b.node));
    const bar = $('makeGroups');
    if (bar) bar.replaceChildren(...GROUPS.map(([id, text]) => el('button', { type: 'button', class: 'make-group g-' + id + (id === state.group ? ' active' : ''), text, 'data-group': id,
      onclick: () => showGroup(id) })));
  }
  $('makeOverlay').classList.remove('hidden');
  paintTab(TABS.find((t) => t.id === tabId) || state.tab || TABS.find((t) => t.id === memLoad().tab) || TABS[0]);
  loadRecent();
  if (!state.opened) { state.opened = true; const g = memLoad().group; if (GROUPS.some(([id]) => id === g)) state.group = g; }
  applyFilter();
  if (!state.caps) ui().api('/api/capabilities').then((caps) => {
    state.caps = caps || {};
    for (const b of state.buttons) { const m = missingFor(TABS.find((t) => t.id === b.id)); b.node.classList.toggle('unavailable', m.length > 0); if (m.length) b.node.setAttribute('title', 'This FFmpeg build is missing: ' + m.join(', ')); }
    if (state.tab && !state.busy) paintTab(state.tab);
  }).catch(() => { state.caps = {}; });
}
function close() { $('makeOverlay').classList.add('hidden'); }

const on = (id, type, fn) => { const node = $(id); if (node) node.addEventListener(type, fn); };
on('openMake', 'click', () => open());
on('makeFromStudio', 'click', () => { if (window.SkellyClips) window.SkellyClips.close(); open(); });
on('makeClose', 'click', close);
on('makeSearch', 'input', () => search($('makeSearch').value));
on('makeTabs', 'keydown', (e) => {
  if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
  const rank = (b) => GROUPS.findIndex(([id]) => id === groupOf(b.id));
  const shown = state.buttons.filter((b) => !b.node.classList.contains('hidden')).sort((a, b) => rank(a) - rank(b)); const at = shown.findIndex((b) => state.tab && b.id === state.tab.id);
  const next = shown[(at + (e.key === 'ArrowRight' ? 1 : shown.length - 1)) % shown.length];
  if (next && !state.busy) { e.preventDefault && e.preventDefault(); paintTab(TABS.find((t) => t.id === next.id)); next.node.focus && next.node.focus(); }
});
const overlay = $('makeOverlay');
if (overlay) {
  overlay.addEventListener('dragover', (e) => { if (e.preventDefault) e.preventDefault(); overlay.classList.add('dragging'); });
  overlay.addEventListener('dragleave', (e) => { if (!e.relatedTarget) overlay.classList.remove('dragging'); });
  overlay.addEventListener('drop', (e) => { if (e.preventDefault) e.preventDefault(); overlay.classList.remove('dragging'); dropFiles(e.dataTransfer && e.dataTransfer.files); });
}
document.addEventListener('keydown', (e) => {
  const o = $('makeOverlay'), box = $('makeSearch');
  if (e.key === '/' && o && !o.classList.contains('hidden') && box && !/^(INPUT|TEXTAREA|SELECT)$/.test((e.target && e.target.tagName) || '')) { if (e.preventDefault) e.preventDefault(); box.focus(); }
});
document.addEventListener('keydown', (e) => { const o = $('makeOverlay'); if (e.key === 'Escape' && o && !o.classList.contains('hidden')) close(); });

window.SkellyMake = { open, close, TABS, extras, GROUPS, groupOf, search, dropFiles, fitsKind };
})();
