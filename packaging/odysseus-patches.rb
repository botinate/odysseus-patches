# Homebrew formula for odysseus-patches.
#
# It lives in a tap repo, not here. To publish:
#   1. Create a repo named `homebrew-tap` under your GitHub account (botinate).
#   2. Put this file at  Formula/odysseus-patches.rb  in that repo.
#   3. After a PyPI release, fill in `url` + `sha256` for the new version
#      (from https://pypi.org/project/odysseus-patches/#files — the sdist
#      `.tar.gz`). `brew bump-formula-pr` can automate this.
#
# Then users install with:
#   brew install botinate/tap/odysseus-patches
#
# odysseus-patches is stdlib-only (no runtime dependencies), so the formula
# just drops the package into its own virtualenv against Homebrew's python.

class OdysseusPatches < Formula
  include Language::Python::Virtualenv

  desc "Apply and manage upstream Odysseus PR patches on a self-hosted install"
  homepage "https://github.com/botinate/odysseus-patches"
  # url + sha256 are filled per release from the PyPI sdist:
  url "https://files.pythonhosted.org/packages/6a/fb/39a73b5db58d5a2191bbebe52b2670965975e3e6feb5b88f2b9a57264a2f/odysseus_patches-0.3.0.tar.gz"
  sha256 "f75603a3a41e29252ce263398d07fa349d5766728883438dfa79d3d9ad1bd9d4"
  license "AGPL-3.0-or-later"

  depends_on "python@3.12"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "usage", shell_output("#{bin}/odysseus-patches --help")
  end
end
