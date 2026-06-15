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
  url "https://files.pythonhosted.org/packages/18/93/d5b51e2cf4f1b1cba8c8d06181c2e9f41d4f2a034d117eaf6153d2ed5559/odysseus_patches-0.3.2.tar.gz"
  sha256 "811fa6340abb0223b61c5a995e6d9de4881c373729f283c075bc09d2c8239c7b"
  license "AGPL-3.0-or-later"

  depends_on "python@3.12"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "usage", shell_output("#{bin}/odysseus-patches --help")
  end
end
