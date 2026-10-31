# Revue de code - octobre 2026

Revue complète de la branche `main` au commit `530abda` (« Serve the web pages on
port 80 by default ») : tout le Python (`photoboothapp.py`, `libs/`, `tools/`,
`firmware/`), l'installeur (`install.sh`, `setup/`), les pages web et les tests.

**Méthode.** Lecture du code ; exécution de la suite de tests (`xvfb-run -a
python -m pytest test/` : 1006 réussis, 1 échec intermittent) ; reproduction des
défauts importants par un script quand c'était possible sans matériel ; lecture
des sources de pycups pour le comportement de CUPS.

**Appréciation générale.** Le code est d'une qualité nettement au-dessus de la
moyenne : chaque décision est expliquée en commentaire, la configuration
retombe sur une valeur sûre au lieu d'empêcher le démarrage, les chemins venus
du réseau sont résolus avant d'être servis (`libs/webserver/paths.py`), la
connexion admin est limitée en essais et le cookie lié au mot de passe, les
écritures de fichiers sont atomiques presque partout, et les deux langues ont
exactement les mêmes 672 clés. Les points ci-dessous sont donc surtout des cas
limites, mais quatre d'entre eux peuvent arrêter le photobooth ou perdre des
photos en pleine soirée.

## Synthèse

| # | Gravité | Sujet | Fichier |
| --- | --- | --- | --- |
| 1 | Haute | Un `%` saisi dans le formulaire admin empêche le démarrage | `libs/config.py:76` |
| 2 | Haute | Une image de 100 Ko envoyée depuis un téléphone peut épuiser la mémoire | `libs/remote_store.py:305` |
| 3 | Haute | Une nouvelle session peut écrire dans `DCIM/tmp` avant que la précédente y soit sauvegardée | `photoboothapp.py:617`, `:701` |
| 4 | Haute | `cancel_stale_jobs` n'annule jamais rien, et annulerait trop s'il marchait | `libs/device_utils.py:645`, `:722` |
| 5 | Moyenne | Le serveur web n'est jamais relancé si son premier démarrage échoue | `libs/webserver/server.py:684` |
| 6 | Moyenne | `config.ini` et les modèles sont écrits sans fichier temporaire | `libs/webserver/server.py:430`, `api.py:174` |
| 7 | Moyenne | Une webcam débranchée fait tourner un cœur à 100 % | `libs/device_utils.py:81` |
| 8 | Moyenne | Export USB : fichier tronqué jamais recopié, `.stats.json` copié chez l'invité | `libs/usb_transfer.py:161` |
| 9 | Moyenne | SIGTERM (arrêt systemd) n'éteint pas les lumières | `photoboothapp.py:66` |
| 10 | Moyenne | Une prise de vue qui échoue ne remet pas la caméra ni le flash en état | `libs/device_utils.py:116`, `:468`, `:589` |
| 11 | Basse | Test dépendant du temps, échoue de façon intermittente | `test/test_ways_out.py:111` |
| 12 | Basse | Petites anomalies : commentaire déplacé, `except:` nu, imports inutiles, `gvfs-mount`, double `on_entry` | divers |
| 13 | Info | Pas de fichier `LICENSE` alors que le README annonce MIT | racine |
| 14 | Info | Choix de conception à connaître (HTTP, galerie publique, CUPS ouvert) | - |

## Suivi des corrections

Chaque correction est dans son propre commit, avec des tests qui échouent sans
elle. Suite complète après correction : 1037 tests réussis sous Xvfb, plusieurs
fois de suite. Essai de bout en bout du photobooth avec `CAMERA = fake` : il
démarre avec un `%` dans le mot de passe admin et dans celui du Wi-Fi, la
connexion admin fonctionne, une photo de téléphone normale est acceptée et un
PNG annonçant 11000 × 11000 pixels refusé avec son message, et SIGTERM l'arrête
en passant par `on_stop`.

| # | Statut | Commit |
| --- | --- | --- |
| 1 | Corrigé | `955b919` Read config.ini without interpolation, so a % never stops the booth |
| 2 | Corrigé | `1617343` Measure an uploaded image before decoding it |
| 3 | Corrigé | `b4ce0a3` Keep the next session out of DCIM/tmp until the last one has left it |
| 4 | Corrigé | `1d49fbd` Cancel forgotten print jobs once, at startup, and only old ones |
| 5 | Corrigé | `ccba7fa` Keep retrying the web server when its first start fails |
| 6 | Corrigé | `a0ec18f` Replace config.ini and templates in one step |
| 7 | Corrigé | `f16f58f` Let the webcam preview rest when the webcam is gone |
| 8 | Corrigé | `6ad76f1` Copy a photo to a USB drive under a temporary name until it is whole |
| 9 | Corrigé | `2567b2f` Stop cleanly on SIGTERM, not only on Ctrl+C |
| 10 | Corrigé | `916c38f` Leave the camera and the ring light as they were when a capture fails |
| 11 | Corrigé | `3efd5c3` Give the codes' timeout test room to run on a busy machine |
| 12 | Corrigé | `ccba7fa` (commentaire), `446dd28` (`gio`), `577710c` (imports, `on_entry`) |
| 13 | Non corrigé | Le titulaire des droits est à choisir par le propriétaire du projet |
| 14 | Documenté | Section *Security notes* du README ; comportement inchangé |

Remarques apparues en corrigeant :

- **Point 4.** L'annulation des travaux d'impression oubliés, qui n'avait jamais
  fonctionné, fonctionne désormais. Au démarrage du photobooth, les travaux de
  sa file créés depuis plus de 15 minutes sont annulés.
- **Point 9.** Kivy exécute `on_stop` deux fois à l'arrêt : `stop()` puis `run()`
  le déclenchent chacun. C'était déjà le cas pour le redémarrage depuis l'admin,
  et tout ce que fait `on_stop` peut être répété sans dommage.
- **Point 9 sous `cage`.** systemd envoie SIGTERM au compositeur et à
  l'application en même temps. L'application demande son arrêt dans le dixième
  de seconde, mais la fermeture du compositeur peut la précéder ; Kivy reçoit
  alors une demande de fermeture de fenêtre, qui passe elle aussi par `on_stop`.
- **Imports inutilisés.** En plus de ceux du point 12, `pyflakes` en a trouvé
  deux autres (`FileUtils` dans `hardware/fake.py`, `session` dans
  `webserver/gallery.py`), retirés dans le même commit.

## Détail et propositions

### 1. Un `%` dans le formulaire admin empêche le démarrage

**Problème.** `Config` lit `config.ini` avec l'interpolation par défaut de
`configparser`, pour laquelle `%` introduit une référence. Le formulaire admin
(`config_form.py`) écrit les valeurs telles quelles, et lit le fichier sans
interpolation. Seuls les textes de l'événement étaient protégés (`raw=True`).

**Reproduction.** Enregistrer `ADMIN_PASSWORD = Soirée%2026!x` ou
`WIFI_PASSWORD = 50%off` par le formulaire, puis redémarrer :
`get_admin_password()` lève `InterpolationSyntaxError` pendant l'étape de
démarrage `_start_services`, l'application s'arrête, systemd la relance, et ainsi
de suite. Le serveur web ne démarre jamais : impossible de corriger depuis le
navigateur.

**Correctif proposé.** Lire sans interpolation, comme le fait déjà le formulaire.
Rien dans le projet n'utilise l'interpolation, et `DATE_FORMAT` est déjà lu brut.

```python
self.config = configparser.ConfigParser(interpolation=None)
```

Effet de bord : une valeur écrite à la main avec `%%` pour « échapper » un `%`
est désormais lue avec ses deux `%` - ce qui était déjà le cas côté formulaire
et côté serveur web (`_refresh_admin_password_from_config`), donc la lecture
devient cohérente partout.

### 2. Bombe de décompression sur `/remote/upload`

**Problème.** Une photo envoyée depuis un téléphone est contrôlée sur sa taille
(12 Mo) et ses premiers octets, puis décodée par `cv2.imread`. Le décodage
alloue largeur × hauteur × 3 octets quel que soit le poids du fichier. La seule
limite est celle d'OpenCV, 2^30 pixels.

**Reproduction.** Un PNG de 109 Ko annonçant 30000 × 30000 pixels passe les deux
contrôles ; `cv2.imread` demanderait 2,7 Go. Sur un Pi, le noyau tue le
processus - et le serveur web avec lui. N'importe quel invité du réseau peut le
faire dès que `REMOTE_CAPTURE` est activé. La photo d'accueil envoyée depuis
l'admin (`admin.py`, `cv2.imdecode`) a le même défaut, réservé à l'opérateur.

**Correctif proposé.** Lire les dimensions dans l'en-tête avec Pillow avant de
décoder, comme `read_asset` le fait déjà pour les images des modèles, et refuser
au-delà de 100 mégapixels (300 Mo une fois décodés, bien au-dessus de ce qu'un
téléphone envoie sous la limite de 12 Mo) :

```python
# libs/file_utils.py
MAX_DECODED_PIXELS = 100_000_000

def decoded_size(data):
    """(largeur, hauteur) annoncées par l'en-tête, ou None."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            return image.size
    except Exception:
        return None
```

Puis, dans `RemoteStore._store_image` et dans l'envoi de la photo d'accueil,
refuser avant tout décodage une image illisible ou trop grande, avec un message
traduit (`web.remote.error.too_many_pixels`).

### 3. Deux sessions dans le même `DCIM/tmp`

**Problème.** La session d'un invité est écrite en arrière-plan
(`finalize_session`) quand il quitte l'écran de revue. L'écran d'accueil attend
la fin de ce travail avant de vider `tmp` (`start.py:632`), mais deux chemins
n'attendent pas :

- choisir une photo envoyée par téléphone lance `stage_remote_photo`, qui vide
  `tmp` aussitôt (`photoboothapp.py:617`) : les fichiers de l'invité précédent
  peuvent disparaître avant d'avoir été déplacés dans sa session ;
- toucher l'écran puis déclencher : `trigger_shot` (`photoboothapp.py:701`)
  écrit `capture-0.jpg` par-dessus celle de l'invité précédent. Avec les filtres
  et des photos de reflex, l'écriture de la session peut dépasser les 5 s du
  compte à rebours, et la photo du nouvel invité finit dans la session de
  l'ancien.

Déduit du code, non reproduit sur un Pi.

**Correctif proposé.**

- `start_photo_task` exécute les tâches l'une après l'autre : une tâche attend
  la fin de celles lancées avant elle. Une erreur d'une tâche précédente n'est
  plus attribuée à la suivante.
- `start_session` attend, si besoin, que la session précédente soit écrite
  (tâches photo et traitement en cours), vide `tmp`, puis seulement passe au
  premier écran. Un second toucher pendant l'attente est ignoré ; l'attente est
  abandonnée si l'écran d'accueil est quitté entre-temps.

### 4. `cancel_stale_jobs`

**Problème.** La fonction cherche les clés `printer-uri` et `printer-name` dans
les travaux renvoyés par `getJobs()`. Un travail CUPS n'a pas ces attributs (le
sien s'appelle `job-printer-uri`), et sans `requested_attributes` CUPS ne
renvoie que `job-id` et `job-uri` (vérifié dans les sources de pycups 2.0.4) :
rien n'est jamais annulé.

Mais elle est appelée dans le constructeur de `CupsPrinter`, que
`reset_devices()` reconstruit après chaque échec de prise de vue. Corrigée
naïvement, elle annulerait en pleine soirée l'impression d'un invité précédent
en attente de papier, ou en cours si l'opérateur redémarre depuis l'admin.

**Correctif proposé.**

- demander `job-printer-uri` et `time-at-creation`, et comparer sur
  `job-printer-uri` ;
- n'annuler que les travaux plus vieux que 15 minutes : bien plus long que ce
  qu'un invité attend devant l'écran d'impression (attente de l'imprimante + 3
  minutes par feuille), donc seuls les travaux réellement oubliés partent ;
- ne l'appeler qu'au démarrage de l'application (`_open_devices`), plus à chaque
  reconstruction des périphériques.

### 5. Serveur web jamais relancé après un premier échec

**Problème.** Le chien de garde qui relance le serveur n'est démarré qu'après un
premier démarrage réussi (`server.py:684`). Si le port ou l'adresse n'est pas
disponible au démarrage (adresse `WEB_HOST` pas encore attribuée, ancien
processus qui tient le port), galerie et admin restent indisponibles toute la
soirée. Le commentaire de `photoboothapp.py:358` parle encore du point d'accès
Wi-Fi, retiré depuis.

**Correctif proposé.** Démarrer le chien de garde aussi après un échec : il
réessaie déjà avec un délai croissant (5 s, 15 s, 1 min, 5 min) puis abandonne.
Mettre le commentaire et le message de journal à jour.

### 6. Écritures non atomiques

**Problème.** `_save_config_text` et l'enregistrement d'un modèle ouvrent le
fichier en écriture (ce qui le vide) puis écrivent. Une coupure de courant entre
les deux laisse un `config.ini` vide : le photobooth redémarre avec les valeurs
par défaut et sans mot de passe admin. Le reste du projet passe déjà par un
fichier temporaire et `os.replace`.

**Correctif proposé.** Un `FileUtils.write_text(path, text)` qui écrit dans un
fichier temporaire du même dossier, le synchronise sur disque, reprend les
permissions du fichier remplacé (`config.ini` contient le mot de passe) et le met
en place avec `os.replace`. L'utiliser pour `config.ini` et les modèles. Le nom
temporaire ne finit pas par `.json`, pour que le chargement des modèles ne le
prenne jamais pour l'un d'eux.

### 7. Webcam débranchée : boucle sans pause

**Problème.** Quand la webcam disparaît, `read()` renvoie `False` immédiatement
et la boucle d'aperçu de `Cv2Camera` recommence sans dormir. La version Pi
Camera a déjà reçu ce correctif.

**Correctif proposé.** Dormir une période d'image quand aucune image n'est lue.

### 8. Export USB

**Problème.** `shutil.copy2` écrit directement le fichier final : une clé retirée
pendant la copie laisse un fichier tronqué, que les exports suivants sautent
parce qu'il « existe déjà ». L'export copie aussi les fichiers cachés du dossier
de sauvegarde, dont `.stats.json` (statistiques de la soirée).

**Correctif proposé.** Copier sous un nom `.part`, puis renommer ; ignorer les
fichiers et dossiers cachés.

### 9. Arrêt par systemd

**Problème.** Seul SIGINT (Ctrl+C) est intercepté. `systemctl stop`, un
redémarrage ou une mise à jour envoient SIGTERM : Python s'arrête sans exécuter
`on_stop`, l'anneau LED garde sa dernière couleur et les chevrons pilotés par le
Pi leur dernier niveau.

**Correctif proposé.** Intercepter SIGTERM comme SIGINT, et demander à
l'application de s'arrêter proprement plutôt que de quitter depuis le
gestionnaire de signal : le gestionnaire lève un drapeau, une horloge Kivy le
lit et appelle `stop()`, ce qui exécute `on_stop` (lumières éteintes, caméra
libérée, serveur arrêté). Ne pas appeler Kivy depuis le gestionnaire lui-même,
qui peut interrompre le fil principal n'importe où. Un second signal quitte
immédiatement, comme avant.

### 10. Prise de vue qui échoue

**Problème.** Aucune des trois méthodes `capture()` n'utilise `try/finally` :

- `Cv2Camera` et `Picamera2Camera` n'éteignent pas l'anneau LED (`flash_fn(stop=True)`) ;
- `Picamera2Camera` reste dans la configuration photo, et l'aperçu tourne
  ensuite sur cette configuration ;
- `Gphoto2Camera` ne remet pas les réglages d'aperçu du reflex.

La reconstruction des périphériques après l'échec limite l'impact, mais
l'anneau reste blanc jusque-là.

**Correctif proposé.** `try/finally` autour de la prise de vue ; pour la Pi
Camera, revenir en configuration d'aperçu avant de laisser remonter l'erreur,
sans masquer l'erreur d'origine.

### 11. Test intermittent

`test_a_touch_gives_the_whole_delay_back` laisse 20 ms de marge entre un délai de
60 ms et deux attentes de 40 ms. Il a échoué une fois sur six quand toute la suite
tourne. **Proposé :** mêmes proportions, délais dix fois plus longs (200 ms de
marge).

### 12. Petites anomalies

- `server.py:26` : le commentaire sur les mots de passe interdits est placé
  au-dessus du délai du chien de garde. Le remettre à sa place.
- `device_utils.py:33` : `except:` nu, qui attrape aussi `KeyboardInterrupt` ;
  `except Exception:`. Le même fichier importe `subprocess` sans s'en servir et
  `numpy` deux fois.
- `gphoto2.py:244` : `gvfs-mount` n'existe plus sur les systèmes actuels ;
  `gio mount -s gphoto2`, sans attendre plus de quelques secondes et sans
  échouer si `gio` est absent.
- `photoboothapp.py:387` : l'écran demandé au démarrage reçoit `on_entry()` deux
  fois, la seconde avec ses paramètres. Sans effet aujourd'hui (l'écran d'erreur
  annule sa première minuterie), mais un seul appel suffit.

### 13. Licence

Le README annonce la licence MIT mais le dépôt n'a pas de fichier `LICENSE`.
**Non corrigé ici :** le texte MIT nomme le titulaire des droits, ce qui revient
au propriétaire du projet (et aux auteurs d'origine s'il s'agit d'un fork).

### 14. Choix de conception à connaître (non modifiés)

- **HTTP en clair.** Sur un Wi-Fi ouvert ou partagé avec les invités, le mot de
  passe et le cookie admin circulent en clair. Administrer depuis un réseau où
  les invités ne sont pas, ou `WEB_HOST = 127.0.0.1`.
- **Galerie publique.** `/gallery` et les collages sont accessibles à tout le
  réseau quel que soit `SHARE`, qui ne fait que montrer le bouton de partage.
  Restreindre la galerie quand `SHARE = False` changerait le comportement pour
  les invités : à décider par le propriétaire.
- **CUPS ouvert au réseau.** L'installeur lance `cupsctl --remote-admin
  --remote-any` ; l'administration de CUPS reste protégée par le mot de passe du
  compte système.
- **Quotas par téléphone.** Ils sont comptés par cookie, donc contournables par
  un script ; `REMOTE_MAX_PENDING` reste la vraie borne de l'espace disque.

Ces points sont décrits dans la section *Security notes* du README.

### Non retenu

- Les arguments par défaut mutables (`kwargs={}`, 27 occurrences) ne sont jamais
  modifiés : les changer n'apporterait que du bruit.
