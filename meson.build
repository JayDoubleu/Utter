project(
  'utter',
  version: run_command(
    'python3', '-c',
    'import re; print(re.search(r"VERSION = \"([^\"]+)\"", open("src/utter/config.py").read()).group(1))',
    check: true,
  ).stdout().strip(),
  meson_version: '>= 1.0.0',
  license: 'GPL-3.0-or-later',
)

app_id = 'io.github.jaydoubleu.Utter'

python = import('python')
gnome = import('gnome')
py = python.find_installation('python3', required: true)

prefix = get_option('prefix')
bindir = prefix / get_option('bindir')
datadir = prefix / get_option('datadir')
pkgdatadir = datadir / meson.project_name()
moduledir = py.get_install_dir()

conf = configuration_data()
conf.set('PYTHON', py.full_path())
conf.set('VERSION', meson.project_version())
conf.set('APP_ID', app_id)
conf.set('bindir', bindir)
conf.set('pythondir', moduledir)
conf.set('pkgdatadir', pkgdatadir)

configure_file(
  input: 'utter.in',
  output: 'utter',
  configuration: conf,
  install: true,
  install_dir: bindir,
  install_mode: 'rwxr-xr-x',
)

subdir('data')
subdir('src')

gnome.post_install(
  glib_compile_schemas: true,
  gtk_update_icon_cache: true,
  update_desktop_database: true,
)
