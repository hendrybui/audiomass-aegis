(function (w, d, PKAudioEditor) {
  'use strict';

  var params = new URLSearchParams(w.location.search);
  if (params.get('embed') !== '1') return;

  var audioUrl = params.get('audio');
  var stemName = params.get('stem') || 'audio';

  // Suppress welcome dialog
  if (w.localStorage) {
    w.localStorage.setItem('k', '1');
  }

  // Hide toolbar after UI initializes
  setTimeout(function () {
    var header = d.querySelector('.pk_tb');
    if (header) header.style.display = 'none';

    var tmpMsg = d.querySelector('.pk_tmpMsg');
    if (tmpMsg) tmpMsg.style.display = 'none';
  }, 500);

  // Load audio once engine is ready
  function loadAudio() {
    if (!PKAudioEditor || !PKAudioEditor.engine || !audioUrl) return;

    w.parent.postMessage({ type: 'audiomass-ready', payload: { stem: stemName } }, '*');

    setTimeout(function () {
      PKAudioEditor.engine.LoadURL(audioUrl);

      PKAudioEditor.listenFor('DidLoadFile', function () {
        w.parent.postMessage({
          type: 'audiomass-loaded',
          payload: {
            stem: stemName,
            duration: PKAudioEditor.engine.wavesurfer.getDuration(),
          },
        }, '*');
      });
    }, 300);
  }

  // Wait for PKAudioEditor.init to complete
  if (PKAudioEditor.engine && PKAudioEditor.engine.wavesurfer) {
    loadAudio();
  } else {
    var check = setInterval(function () {
      if (PKAudioEditor.engine && PKAudioEditor.engine.wavesurfer) {
        clearInterval(check);
        loadAudio();
      }
    }, 100);
  }

  // Listen for commands from parent
  w.addEventListener('message', function (event) {
    var data = event.data || {};
    switch (data.type) {
      case 'load-audio':
        if (data.payload && data.payload.url && PKAudioEditor.engine) {
          PKAudioEditor.engine.LoadURL(data.payload.url);
        }
        break;
    }
  });
})(window, document, PKAudioEditor);
