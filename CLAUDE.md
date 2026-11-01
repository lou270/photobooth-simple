# CLAUDE.md

## Git
- Fusionner dans main par avance rapide (`git merge --ff-only`) quand la branche
  n'a qu'un ou deux commits ; sinon un commit de merge `--no-ff`.
- Ne jamais pousser sans qu'on le demande.

## Carte du code

De quoi s'orienter sans tout relire. L'arborescence commentée est dans
README.md (« Project layout »). Code, commentaires et commits sont en anglais.

### Démarrage : `photoboothapp.py`
- `PhotoboothApp.__init__` lit `config.ini` (`libs/config.py`), fixe la langue
  et les délais (`TIMINGS`), crée l'anneau LED et les chevrons.
- `on_start` enchaîne cinq étapes derrière `LoadingScreen` : `_open_devices`
  (`DeviceUtils`), `_load_templates`, `_open_storage` (`SessionStorage`,
  `StatsStore`, `RemoteStore`), `_start_services` (`UsbTransfer`, `WebServer`),
  `_build_screens` (`ScreenMgr`). Si une étape lève une exception, la borne
  affiche l'échec et redémarre quand on appuie sur OK.
- L'app sert de façade : écrans et serveur web passent par ses méthodes
  (`trigger_shot`, `trigger_collage`, `trigger_print`, `finalize_session`,
  `stage_remote_photo`, `request_restart`…), pas par les périphériques.

### Parcours d'une session : `libs/screens/`
START → SELECT_FORMAT (sauté s'il n'y a qu'un template) → COUNTDOWN →
CONFIRM_CAPTURE (→ COUNTDOWN pour la photo suivante ou à refaire) →
PROCESSING → REVIEW → PRINTING → START. À côté : ERROR, COPYING (export USB),
REMOTE_GALLERY (photo d'un téléphone → PROCESSING).
- Noms dans `names.py` (`ScreenNames`), construction dans `manager.py`
  (`ScreenMgr`). Échap ramène à l'accueil ; Entrée et Espace appellent
  `on_keyboard_action()` de l'écran courant.
- Chaque écran a `on_entry(kwargs)` et `on_exit()`, appelés par
  `app.transition_to(nom, **kwargs)`.
- Bases dans `base.py` : `BackgroundScreen`, `ColorScreen` et
  `HomeTimeoutMixin` (retour à l'accueil, anneau sur le bouton maison).
- Widgets partagés dans `libs/kivywidgets.py`. Les marges se mesurent avec
  `short_side()`.

### Threads
- Kivy ne se touche que depuis le thread principal. Ailleurs :
  `Clock.schedule_once`, ou `app.request_transition_to` pour changer d'écran.
- Prise de vue et collage : `ProcessRunner` (`libs/core/process_runner.py`),
  un travail suivi à la fois, que les écrans interrogent depuis leur horloge.
  Un travail bloqué dans la caméra est abandonné, puis les périphériques sont
  reconstruits (`reset_devices`).
- Écriture des sessions et photos des téléphones : `app.start_photo_task`,
  les tâches s'exécutent l'une après l'autre, car toutes travaillent dans `DCIM/tmp`.
- Serveur web, export USB et rechargement des templates ont leurs propres threads.

### Où vit quoi
- Caméras : contrat dans `libs/hardware/camera.py`, backends Picamera2,
  gPhoto2 (via `libs/gphoto2.py`) et OpenCV dans `libs/device_utils.py`,
  `FakeCamera` dans `libs/hardware/fake.py` (`CAMERA = fake`). `DeviceUtils`
  regroupe la caméra et l'imprimante CUPS.
- Lumières : `libs/hardware/led.py` (anneau WS2812) et `chevrons.py` (PWM par
  GPIO, ou par un RP2040 avec `firmware/chevrons_rp2040/main.py`). Désactivées
  ou absentes, elles ne font rien.
- Fichiers : `SessionStorage` (`libs/core/storage.py`) écrit dans `DCIM/tmp`
  pendant la session, puis déplace tout dans `DCIM/save/<AAAAMMJJ_HHMMSS>/`.
- Templates : JSON dans `templates/`, validés par `libs/template_schema.py`,
  assemblés par `TemplateCollage` (`libs/template_collage.py`). La page et la
  découpe viennent du PPD de l'imprimante (`libs/print_sizes.py`).
- Web (`libs/webserver/`) : `server.py` (Flask, watchdog, authentification
  admin), puis un blueprint par zone : `gallery.py` (invités), `admin.py`,
  `api.py` (JSON de l'admin et de l'éditeur de templates), `remote.py`
  (téléphone comme appareil photo). Tout chemin venu du réseau passe par
  `paths.py`. Les pages Jinja sont dans `web/`.
- Textes : `locales/en.json` et `locales/fr.json`, lus par `i18n.t('clé.pointée')`
  côté borne comme côté web.
- Délais réglables : `libs/timings.py`. Dans un écran, utiliser `Timing('nom')`
  plutôt qu'une constante, sinon la valeur de `config.ini` est ignorée.

### Ajouter un réglage à config.ini
Le commit e7be01f sert d'exemple :
1. `config.ini.example` : l'option et son commentaire, dans sa section ;
2. `libs/config.py` : un `get_<option>()` avec valeur de repli et bornes ;
3. `libs/webserver/config_form.py` : un champ dans `CONFIG_FORM_SECTIONS`,
   avec le même `default` ;
4. `locales/en.json` et `locales/fr.json` : `label` et `help` sous
   `web.config.<Section>.<OPTION>` ;
5. `photoboothapp.py` : lire la valeur et la transmettre ;
6. `test/test_config.py`. `test/test_config_form.py` vérifie déjà la
   cohérence des défauts, des traductions et de l'exemple.

### Tests et outils
- `python -m pytest test/` tourne sans matériel. Les écrans Kivy ont besoin
  d'un affichage (`xvfb-run -a` sur un Linux sans écran).
- `test/test_screen_conventions.py` interdit `Window.height * 0.0x` et
  `MouseMotionEvent` dans les écrans.
- `tools/` : doctor, splash de démarrage, calibration du zoom ;
  `tools/manual/` : vérifications à lancer à la main sur la borne.

### Installation sur le Pi
`install.sh` s'appuie sur `setup/lib.sh` (blocs gérés, relançable sans
risque) et enregistre ses réponses dans `setup/booth.conf`. Les gabarits
systemd, udev, PAM et NetworkManager sont dans `setup/templates/`. Pour
vérifier une installation : `setup/doctor.sh`. Voir INSTALLATION.md.
