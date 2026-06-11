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
  url "https://files.pythonhosted.org/packages/5b/1a/ae9aaa68e89954f86e3ba984dd1603dca98b78e54dcd48b612b8a6fceac3/odysseus_patches-0.1.0.tar.gz"
  sha256 "8217353c744e262a2f4d211f9bd34e7a3d0b13bb66de6d65b99b37e47ec47f1f"
  license "AGPL-3.0-or-later"

  depends_on "python@3.12"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "usage", shell_output("#{bin}/odysseus-patches --help")
  end
end
